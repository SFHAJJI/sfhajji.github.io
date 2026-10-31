"""The tables of SPEC §1, built with pandas from the documents.

``page_df``, ``line_df`` (the citation unit), ``toc_df``, ``row_df``, ``cross_ref_df``,
``corpus_index`` and the ``parse_coverage`` dict. Everything here is a pure function of the
documents, so the same raw files give the same tables, and ``index_version`` is their hash.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import pandas as pd

from .. import PIPELINE_VERSION
from .blocks import ParsedDocument, fold, parse_html
from .documents import Document, SiteData
from .topics import classify_topic, find_concepts, page_words, shape_of, summary_line

TABLE_NAMES = ("page_df", "line_df", "toc_df", "row_df", "cross_ref_df", "corpus_index")

# Rows are sorted by these keys before hashing and export: the order on disk never depends on
# the order of construction.
SORT_KEYS: dict[str, list[str]] = {
    "page_df": ["doc_id"],
    "line_df": ["doc_id", "line_num"],
    "toc_df": ["doc_id", "start_line", "section_id"],
    "row_df": ["doc_id", "table_id", "line_num"],
    "cross_ref_df": ["doc_id", "line_num", "target_doc_id", "target_anchor", "href"],
    "corpus_index": ["doc_id"],
}

COLUMNS: dict[str, list[str]] = {
    "page_df": ["doc_id", "doc_order", "url", "title", "lang", "n_lines", "n_sections", "n_tables",
                "content_sha256", "fetched_at", "last_modified", "parsing_method", "kind", "category", "raw_files"],
    "line_df": ["doc_id", "line_num", "text", "element", "section_id", "anchor_id", "css_path", "char_count", "is_heading"],
    "toc_df": ["doc_id", "section_id", "level", "parent_id", "title", "breadcrumb", "start_line", "end_line", "anchor_id", "source"],
    "row_df": ["doc_id", "table_id", "line_num", "line_end", "column_headers", "row_cells", "row_serialized"],
    "cross_ref_df": ["doc_id", "line_num", "href", "target_doc_id", "target_anchor", "context"],
    "corpus_index": ["doc_id", "doc_order", "url", "title", "topic", "summary_line", "tags", "n_lines", "lang", "category", "shape"],
}

_STOPWORDS = {
    "fr": "le la les des une un et est pour vous dans pas que qui sur avec votre ce cette au aux du".split(),
    "en": "the and of to you your for is with that this are from have will not".split(),
    "de": "der die das und ist nicht sie mit für den ein eine auch werden sich".split(),
}


@dataclass
class BuiltIndex:
    tables: dict[str, pd.DataFrame]
    coverage: dict[str, Any]


def vote_language(text: str) -> str:
    """Dictionary vote over stopwords when ``<html lang>`` is missing."""
    words = re.findall(r"[a-zäöüß]+", text.lower())
    counts = {lang: sum(1 for w in words if w in set(sw)) for lang, sw in _STOPWORDS.items()}
    best = max(counts.values()) if counts else 0
    if best == 0:
        return "unknown"
    return next(lang for lang in ("fr", "en", "de") if counts[lang] == best)


def _norm_lang(lang: str) -> str:
    lang = (lang or "").strip().lower()[:2]
    return lang if lang in ("fr", "en", "de") else ""


class _Resolver:
    """``href`` → (target_doc_id, target_anchor) for internal links; None for external ones."""

    def __init__(self, documents: list[Document], site_url: str):
        self.site = urlsplit(site_url)
        self.doc_ids = {d.doc_id for d in documents}
        # The site's hash routes: ``#<panel>`` opens a panel, ``#fiche/<id>`` a fiche. Any other
        # fragment is an element id on the current document.
        self.route_ids = {d.doc_id for d in documents if d.kind in ("panel", "page")}
        self.by_path: dict[str, str] = {}
        for d in documents:  # the first document of a page is that path's default target
            self.by_path.setdefault(d.path, d.doc_id)

    def resolve(self, href: str, doc: Document) -> tuple[str, str] | None:
        href = href.strip()
        if href.startswith("#"):
            return self._fragment(href[1:], doc.doc_id, self.by_path.get(doc.path, doc.doc_id))
        u = urlsplit(urljoin(doc.url, href))
        if u.scheme not in ("http", "https") or u.netloc != self.site.netloc:
            return None
        path = u.path or "/"
        target = self.by_path.get(path)
        if target is None and path.endswith("/index.html"):
            target = self.by_path.get(path[: -len("index.html")])
        if target is None:
            return None  # a same-origin file that is not a document (an asset)
        if u.fragment:
            return self._fragment(u.fragment, target, target)
        return target, ""

    def _fragment(self, frag: str, same_doc: str, page_default: str) -> tuple[str, str]:
        if frag.startswith("fiche/") and frag[6:] in self.doc_ids:
            return frag[6:], ""
        if frag in self.route_ids:
            return frag, ""
        if frag.startswith("fiche/"):
            return page_default, frag
        return same_doc, frag


def build_tables(documents: list[Document], data: SiteData | None = None, site_url: str = "", pipeline_version: str = PIPELINE_VERSION) -> BuiltIndex:
    """Parse every document and assemble the six tables plus the coverage dict."""
    site_url = site_url or (documents[0].url if documents else "")
    resolver = _Resolver(documents, site_url)
    parsed: list[tuple[Document, ParsedDocument]] = [(d, parse_html(d.doc_id, d.html)) for d in documents]

    pages, lines, toc, rows, refs = [], [], [], [], []
    for doc, p in parsed:
        text_all = " ".join(ln.text for ln in p.lines)
        lang = _norm_lang(doc.lang_hint) or _norm_lang(p.lang_attr) or vote_language(text_all)
        pages.append({
            "doc_id": doc.doc_id, "doc_order": doc.order, "url": doc.url, "title": p.title, "lang": lang,
            "n_lines": len(p.lines), "n_sections": len(p.headings), "n_tables": p.n_tables,
            "content_sha256": doc.content_sha256, "fetched_at": doc.fetched_at, "last_modified": doc.last_modified,
            "parsing_method": doc.parsing_method, "kind": doc.kind, "category": doc.category, "raw_files": list(doc.raw_files),
        })
        for ln in p.lines:
            lines.append({
                "doc_id": doc.doc_id, "line_num": ln.line_num, "text": ln.text, "element": ln.element,
                "section_id": ln.section_id, "anchor_id": ln.anchor_id, "css_path": ln.css_path,
                "char_count": ln.char_count, "is_heading": bool(ln.is_heading),
            })
        for h in p.headings:
            toc.append({
                "doc_id": doc.doc_id, "section_id": h.section_id, "level": h.level, "parent_id": h.parent_id,
                "title": h.title, "breadcrumb": h.breadcrumb, "start_line": h.start_line, "end_line": h.end_line,
                "anchor_id": h.anchor_id, "source": "headings",
            })
        for r in p.rows:
            rows.append({
                "doc_id": doc.doc_id, "table_id": r.table_id, "line_num": r.line_num, "line_end": r.line_end,
                "column_headers": list(r.column_headers), "row_cells": list(r.row_cells), "row_serialized": r.row_serialized,
            })
        for link in p.links:
            target = resolver.resolve(link.href, doc)
            if target is None:
                continue
            refs.append({
                "doc_id": doc.doc_id, "line_num": link.line_num, "href": link.href,
                "target_doc_id": target[0], "target_anchor": target[1], "context": link.context,
            })

    corpus = _corpus_index(parsed, [pg["lang"] for pg in pages])

    tables = {
        "page_df": _frame(pages, "page_df"),
        "line_df": _frame(lines, "line_df"),
        "toc_df": _frame(toc, "toc_df"),
        "row_df": _frame(rows, "row_df"),
        "cross_ref_df": _frame(refs, "cross_ref_df"),
        "corpus_index": _frame(corpus, "corpus_index"),
    }
    fetched = max((d.fetched_at for d in documents), default="")
    coverage = {
        "pages_total": len(pages),
        "pages_with_text": sum(1 for pg in pages if pg["n_lines"] > 0),
        "lines_total": len(lines),
        "sections_total": len(toc),
        "tables_total": sum(pg["n_tables"] for pg in pages),
        "table_rows_total": len(rows),
        "cross_refs": len(refs),
        "fetched_at": fetched,
        "index_version": "",
        "pipeline_version": pipeline_version,
        "parsing_methods": sorted({pg["parsing_method"] for pg in pages}),
        "data_scripts": list(data.notes) if data else [],
        "documents": {"panel": sum(1 for pg in pages if pg["kind"] == "panel"), "fiche": sum(1 for pg in pages if pg["kind"] == "fiche"), "page": sum(1 for pg in pages if pg["kind"] == "page")},
    }
    coverage["index_version"] = index_version(tables)
    return BuiltIndex(tables=tables, coverage=coverage)


def _frame(records: list[dict[str, Any]], name: str) -> pd.DataFrame:
    df = pd.DataFrame.from_records(records, columns=COLUMNS[name])
    if len(df):
        df = df.sort_values(SORT_KEYS[name], kind="mergesort").reset_index(drop=True)
    return df


def _corpus_index(parsed: list[tuple[Document, ParsedDocument]], langs: list[str]) -> list[dict[str, Any]]:
    """One line per document, written for the router (SPEC §2b)."""
    pre = []
    for (doc, p), lang in zip(parsed, langs):
        headings = [h.title for h in p.headings]
        body = " ".join(ln.text for ln in p.lines)
        topic = classify_topic(p.title, headings, doc.category)
        tags = find_concepts(p.title + " " + " ".join(headings) + " " + body)
        pre.append((doc, p, lang, topic, tags, headings))
    out = []
    for doc, p, lang, topic, tags, headings in pre:
        n_steps = sum(1 for ln in p.lines if ln.element == "li" and re.search(r"(^|> )ol\b", ln.css_path))
        n_questions = sum(1 for h in p.headings if h.level == 3 and h.title.rstrip().endswith("?"))
        shape = shape_of(len(p.headings), p.n_tables, n_steps, n_questions, len(p.lines))
        reader_words = list(doc.reader_words) or [c for c in find_concepts(p.title + " " + " ".join(headings))]
        words = page_words(p.title, headings) or tags[:5]
        same_topic = [o.title for (d2, o, _, t2, _, _) in pre if d2.doc_id != doc.doc_id and t2 == topic and d2.kind == doc.kind]
        if not same_topic:
            same_topic = [o.title for (d2, o, _, t2, _, _) in pre if d2.doc_id != doc.doc_id and t2 == topic]
        out.append({
            "doc_id": doc.doc_id, "doc_order": doc.order, "url": doc.url, "title": p.title, "topic": topic,
            "summary_line": summary_line(p.title, reader_words, words, shape, same_topic),
            "tags": tags, "n_lines": len(p.lines), "lang": lang, "category": doc.category, "shape": shape,
        })
    return out


# ----- canonical form and the hash -----


def _py(value: Any) -> Any:
    """numpy scalars → Python scalars, so json sees plain types."""
    if hasattr(value, "item") and not isinstance(value, (list, dict, str, bytes)):
        try:
            return value.item()
        except (ValueError, AttributeError):
            return value
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


def to_records(df: pd.DataFrame, name: str) -> list[dict[str, Any]]:
    """The table as sorted, JSON-ready records in the SPEC column order."""
    cols = COLUMNS.get(name) or list(df.columns)
    records = [{c: _py(v) for c, v in zip(cols, row)} for row in df[cols].itertuples(index=False, name=None)]
    keys = SORT_KEYS.get(name, [cols[0]])
    records.sort(key=lambda r: tuple(r.get(k) if r.get(k) is not None else "" for k in keys))
    return records


def dumps(obj: Any) -> str:
    """Compact, UTF-8, keys sorted: the one serialisation used for files and for the hash."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def index_version(tables: dict[str, pd.DataFrame]) -> str:
    """sha256 over the sorted contents of the six tables, in a fixed order."""
    h = hashlib.sha256()
    for name in TABLE_NAMES:
        h.update(name.encode("utf-8"))
        h.update(dumps(to_records(tables[name], name)).encode("utf-8"))
    return h.hexdigest()


def doc_text(tables: dict[str, pd.DataFrame], doc_id: str) -> str:
    """Convenience for tests and reports: the page as its lines, folded for matching."""
    df = tables["line_df"]
    return fold(" ".join(df[df["doc_id"] == doc_id]["text"]))
