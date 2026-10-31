"""The site model: which fetched files become which documents.

What we found (2026-10-31): the site is one page of panels (``index.html``, ``<section
class="panel" id="panel-…">``) plus one rubric in its own page (``prevoyance/``). The panels'
static HTML holds titles and lead paragraphs; the content lives in data scripts and the
browser renders it:

- ``app/kb.js``: ``window.KB = {meta, fiches[], faq[], timeline[]}``; a fiche is
  ``{id, titre, cat, resume, tags, corps[str | {h}], tableaux[], aRetenir[], sources[]}``.
- ``app/fiches/*.js``: ``window.FICHES.<id> = {…, guide: {reperes, cas, onglets}}``, the guided
  fiches that ``KB.fiches`` includes by reference.
- ``app/avantages.js``: ``var AVANTAGES = [...]`` with ``MOMENTS`` and ``MODES`` for its labels.
- ``prevoyance/app/questions.js``: ``var ENTREES`` (questions by ``THEMES``, answers with
  ``{plafond}`` marks) and ``prevoyance/app/prevoyance.js``: ``var TABLE`` (the figures).

So a document is: one panel of the home page (``doc_id`` = the panel id, url ``/#<id>``), one
fiche (``doc_id`` = the fiche id, url ``/#fiche/<id>``, rendered as ``#fiche-detail`` shows
it), or one separate page (``doc_id`` = the path's slug). The JS content is rendered into the
same containers the browser fills, then everything goes through the one HTML parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from . import render
from .jsdata import find_assignments, resolve


@dataclass
class Document:
    doc_id: str
    url: str
    path: str  # the site path of the raw page this document comes from
    html: str
    kind: str  # panel | fiche | page
    parsing_method: str  # html_blocks/1 | js_data+html_blocks/1
    raw_files: list[str]
    content_sha256: str
    fetched_at: str
    last_modified: str
    order: int
    lang_hint: str = ""
    category: str = ""
    reader_words: list[str] = field(default_factory=list)  # the fiche's own search tags


@dataclass
class SiteData:
    """What the data scripts contained, by name; ``notes`` says where each piece was found."""

    fiches: list[dict[str, Any]] = field(default_factory=list)
    faq: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    avantages: list[dict[str, Any]] = field(default_factory=list)
    moments: list[Any] = field(default_factory=list)
    modes: dict[str, Any] = field(default_factory=dict)
    questions: dict[str, Any] = field(default_factory=dict)
    prevoyance_table: dict[str, Any] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)  # role → raw file name
    notes: list[str] = field(default_factory=list)


def extract_site_data(scripts: dict[str, tuple[str, str]]) -> SiteData:
    """``scripts``: site path → (raw file name, text). Reads the literals; executes nothing."""
    data = SiteData()
    per_script = {path: find_assignments(text) for path, (_, text) in scripts.items()}
    env: dict[str, Any] = {}
    for found in per_script.values():
        for name, value in found.items():
            env.setdefault(name, value)
            env.setdefault(name.rsplit(".", 1)[-1], value)

    for path, found in per_script.items():
        file = scripts[path][0]
        kb = found.get("window.KB")
        if isinstance(kb, dict):
            kb = resolve(kb, env)
            data.fiches = [f for f in kb.get("fiches") or [] if isinstance(f, dict)]
            data.faq = [q for q in kb.get("faq") or [] if isinstance(q, dict)]
            data.timeline = [t for t in kb.get("timeline") or [] if isinstance(t, dict)]
            data.files["kb"] = file
            data.notes.append(f"{path}: window.KB with {len(data.fiches)} fiches, {len(data.faq)} faq, {len(data.timeline)} timeline phases")
        guided = [n for n in found if n.startswith("window.FICHES.")]
        if guided:
            data.files.setdefault("fiches", file)
            data.notes.append(f"{path}: guided fiche(s) {', '.join(n.split('.')[-1] for n in guided)}")
        if isinstance(found.get("AVANTAGES"), list):
            data.avantages = resolve(found["AVANTAGES"], env)
            data.moments = resolve(found.get("MOMENTS") or [], env)
            data.modes = resolve(found.get("MODES") or {}, env)
            data.files["avantages"] = file
            data.notes.append(f"{path}: AVANTAGES with {len(data.avantages)} cards in {len(data.moments)} moments")
        if isinstance(found.get("ENTREES"), list):
            local = dict(env)
            local.update(found)
            data.questions = {"themes": resolve(found.get("THEMES") or [], local), "entrees": resolve(found["ENTREES"], local)}
            data.files["questions"] = file
            data.notes.append(f"{path}: ENTREES with {len(data.questions['entrees'])} questions in {len(data.questions['themes'])} themes")
        if isinstance(found.get("TABLE"), dict) and "leviers" in found["TABLE"]:
            data.prevoyance_table = resolve(found["TABLE"], env)
            data.files["prevoyance"] = file
            data.notes.append(f"{path}: TABLE with {len(data.prevoyance_table.get('leviers') or [])} deductible items")
    return data


def _fill(container: Tag | None, fragment: str) -> bool:
    """Replace the content of ``container`` by the rendered fragment (as the browser does)."""
    if container is None or not fragment:
        return False
    container.clear()
    frag = BeautifulSoup(fragment, "html.parser")
    for child in list(frag.contents):
        container.append(child)
    return True


def _wrap(lang: str, inner: str) -> str:
    return f'<!DOCTYPE html>\n<html lang="{lang}"><body><main>{inner}</main></body></html>'


def build_documents(raw_dir: Path, manifest: dict) -> tuple[list[Document], SiteData]:
    """Turn the fetched files into documents, in site order (home panels, fiches, other pages)."""
    raw_dir = Path(raw_dir)
    resources = manifest.get("resources", [])
    pages = [r for r in resources if r["kind"] == "html" and r.get("http_status") == 200 and r.get("file")]
    pages.sort(key=lambda r: (len(r["path"]), r["url"]))  # the home page first
    scripts: dict[str, tuple[str, str]] = {}
    for r in resources:
        if r["kind"] == "script" and r.get("http_status") == 200 and r.get("file"):
            scripts[r["path"]] = (r["file"], (raw_dir / r["file"]).read_text(encoding="utf-8", errors="replace"))
    data = extract_site_data(scripts)

    docs: list[Document] = []
    order = 0
    for page in pages:
        html = (raw_dir / page["file"]).read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")
        html_tag = soup.find("html")
        lang = (html_tag.get("lang") or "") if html_tag else ""
        base = dict(
            path=page["path"], content_sha256=page["content_sha256"], fetched_at=page["fetched_at"],
            last_modified=page.get("last_modified", ""), lang_hint=lang,
        )
        panels = soup.select("section.panel[id^=panel-]")
        if panels:
            for panel in panels:
                pid = panel["id"][len("panel-"):]
                files = [page["file"]]
                injected = _inject_panel(panel, pid, data, files)
                order += 1
                docs.append(Document(
                    doc_id=pid, url=page["url"] + "#" + pid, html=_wrap(lang, str(panel)), kind="panel",
                    parsing_method="js_data+html_blocks/1" if injected else "html_blocks/1",
                    raw_files=files, order=order, **base,
                ))
                if pid == "fiches":
                    for f in data.fiches:
                        order += 1
                        docs.append(_fiche_document(f, page, data, order, lang, base))
        else:
            from .fetch import slug_of

            files = [page["file"]]
            injected = _inject_page(soup, data, files)
            order += 1
            docs.append(Document(
                doc_id=slug_of(page["path"]), url=page["url"], html=str(soup), kind="page",
                parsing_method="js_data+html_blocks/1" if injected else "html_blocks/1",
                raw_files=files, order=order, **base,
            ))

    ids = [d.doc_id for d in docs]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate doc_id: {dupes}")
    return docs, data


def _inject_panel(panel: Tag, pid: str, data: SiteData, files: list[str]) -> bool:
    """Fill the panel's empty containers with the JS content the browser renders there."""
    if pid == "fiches" and data.fiches:
        files.append(data.files.get("kb", ""))
        return _fill(panel.find(id="fiches-grid"), render.render_fiche_list(data.fiches))
    if pid == "parcours" and data.timeline:
        files.append(data.files.get("kb", ""))
        return _fill(panel.find(id="timeline"), render.render_timeline(data.timeline))
    if pid == "faq" and data.faq:
        files.append(data.files.get("kb", ""))
        return _fill(panel.find(id="faq-liste"), render.render_faq(data.faq, data.fiches))
    if pid == "avantages" and data.avantages:
        files.append(data.files.get("avantages", ""))
        return _fill(panel.find(id="avantages-grille"), render.render_avantages(data.avantages, data.moments, data.modes))
    return False


def _inject_page(soup: BeautifulSoup, data: SiteData, files: list[str]) -> bool:
    """The separate ``prevoyance/`` page: its figures, questions and sources."""
    done = False
    if data.prevoyance_table and soup.find(id="acc-apercu") is not None:
        files.append(data.files.get("prevoyance", ""))
        done |= _fill(soup.find(id="acc-apercu"), render.render_prevoyance_leviers(data.prevoyance_table))
        done |= _fill(soup.find(id="pied-sources"), render.render_sources_list(data.prevoyance_table.get("sources") or []))
    if data.questions and soup.find(id="q-liste") is not None:
        files.append(data.files.get("questions", ""))
        marks = render.prevoyance_marks(data.prevoyance_table)
        done |= _fill(soup.find(id="q-liste"), render.render_prevoyance_questions(data.questions, marks))
    return done


def _fiche_document(f: dict[str, Any], page: dict, data: SiteData, order: int, lang: str, base: dict) -> Document:
    files = [page["file"], data.files.get("kb", "")]
    if f.get("guide") and data.files.get("fiches"):
        files.append(data.files["fiches"])
    inner = f'<section class="panel" id="panel-fiches"><div id="fiche-detail" class="detail">{render.render_fiche(f)}</div></section>'
    return Document(
        doc_id=str(f["id"]), url=page["url"] + "#fiche/" + str(f["id"]), html=_wrap(lang, inner), kind="fiche",
        parsing_method="js_data+html_blocks/1", raw_files=[x for x in files if x], order=order,
        category=str(f.get("cat") or ""), reader_words=[str(t) for t in f.get("tags") or []], **base,
    )
