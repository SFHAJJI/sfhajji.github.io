"""HTML → lines, headings, table rows and links, for one document.

The line is the citation unit (SPEC §0.3), so this module decides what a line is: one
visible block of text, in reading order, verbatim but whitespace-squashed. A block element
whose content is inline text is one line. A block that contains other blocks is not a line;
its children are (and a run of inline text between two child blocks is a line of its own, so
nothing visible is lost). Headings become sections; table rows become rows; ``<a href>``
become cross references. Everything is computed from the DOM once; downstream reads tables.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

# The element vocabulary of line_df (SPEC §1). Other block tags map onto it below.
LINE_ELEMENTS = ("h1", "h2", "h3", "h4", "p", "li", "td", "th", "caption", "blockquote", "dt", "dd")

# Not content: code, styling, media, and form controls (the site's inputs and buttons).
SKIP_TAGS = frozenset(
    "script style noscript template svg head iframe button input select textarea label option "
    "datalist canvas video audio picture source img map area object embed meta link title".split()
)

# Containers whose children are walked. Anything else is inline and stays inside its line.
BLOCK_TAGS = frozenset(
    "html body main header footer nav section article aside div figure figcaption details summary "
    "ul ol dl table thead tbody tfoot tr pre address hr form fieldset legend h5 h6".split()
) | frozenset(LINE_ELEMENTS)

# A run of inline text directly inside one of these is reported with the mapped element.
_KIND = {"h5": "h4", "h6": "h4"}
for _t in BLOCK_TAGS:
    _KIND.setdefault(_t, _t if _t in LINE_ELEMENTS else "p")

HEADING_LEVEL = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}


@dataclass
class Line:
    line_num: int
    text: str
    element: str
    section_id: str
    anchor_id: str
    css_path: str
    char_count: int
    is_heading: bool
    tag: str = ""  # the real tag, for the table and heading passes


@dataclass
class Heading:
    section_id: str
    level: int
    parent_id: str
    title: str
    breadcrumb: str
    start_line: int
    end_line: int
    anchor_id: str


@dataclass
class TableRow:
    table_id: str
    line_num: int  # first cell of the row
    line_end: int  # last cell of the row
    column_headers: list[str]
    row_cells: list[str]
    row_serialized: str


@dataclass
class Link:
    line_num: int
    href: str
    text: str
    context: str


@dataclass
class ParsedDocument:
    doc_id: str
    title: str
    lang_attr: str
    lines: list[Line] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    rows: list[TableRow] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    n_tables: int = 0


def squash(text: str) -> str:
    """Whitespace-squashed: every run of Unicode whitespace (nbsp included) becomes one space."""
    return " ".join(text.split())


def fold(text: str) -> str:
    """Lowercase, accents stripped: for matching only, never for display."""
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in nfd if not unicodedata.combining(ch))


def inline_text(node: Tag | NavigableString) -> str:
    """The text of an inline subtree, skipping non-content tags; ``<br>`` counts as a space."""
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    if node.name in SKIP_TAGS:
        return ""
    if node.name == "br":
        return " "
    return "".join(inline_text(c) for c in node.children)


def css_path(node: Tag) -> str:
    """A short selector from the nearest ancestor with an id down to ``node``.

    ``tag#id`` or ``tag.first-class``, with ``:nth-of-type`` when siblings share the tag. Stops
    at the first id so the path survives changes elsewhere on the page.
    """
    parts: list[str] = []
    cur: Tag | None = node
    while cur is not None and cur.name not in ("[document]", "html"):
        part = cur.name
        node_id = cur.get("id")
        classes = cur.get("class") or []
        if node_id:
            part += f"#{node_id}"
        elif classes:
            part += f".{classes[0]}"
        parent = cur.parent
        if parent is not None and not node_id:
            same = [s for s in parent.children if isinstance(s, Tag) and s.name == cur.name]
            if len(same) > 1:
                part += f":nth-of-type({same.index(cur) + 1})"
        parts.append(part)
        if node_id:
            break
        cur = parent
    return " > ".join(reversed(parts))


class _Walker:
    """One pass over the DOM in document order; keeps the running anchor and line counter."""

    def __init__(self, doc: ParsedDocument):
        self.doc = doc
        self.anchor = ""
        self.section_id = ""
        self.heading_stack: list[Heading] = []
        self.n = 0

    # ----- lines -----

    def emit(self, container: Tag, run: list) -> Line | None:
        text = squash("".join(inline_text(x) for x in run))
        if not text:
            return None
        tag = container.name
        element = _KIND.get(tag, "p")
        self.n += 1
        line = Line(
            line_num=self.n,
            text=text,
            element=element,
            section_id=self.section_id,
            anchor_id=self.anchor,
            css_path=css_path(container),
            char_count=len(text),
            is_heading=element in HEADING_LEVEL,
            tag=tag,
        )
        if line.is_heading:
            self.open_section(line)
            line.section_id = self.section_id
        self.doc.lines.append(line)
        self.collect_links(line, run)
        return line

    def collect_links(self, line: Line, run: list) -> None:
        for node in run:
            if not isinstance(node, Tag):
                continue
            anchors = [node] if node.name == "a" else node.find_all("a")
            for a in anchors:
                href = (a.get("href") or "").strip()
                if not href:
                    continue
                text = squash(inline_text(a))
                i = line.text.find(text) if text else -1
                if i < 0:
                    context = line.text[:60]
                else:
                    context = line.text[max(0, i - 30) : i + len(text) + 30]
                self.doc.links.append(Link(line.line_num, href, text, context))

    # ----- sections -----

    def open_section(self, line: Line) -> None:
        level = HEADING_LEVEL[line.element]
        while self.heading_stack and self.heading_stack[-1].level >= level:
            self.heading_stack.pop()
        parent = self.heading_stack[-1] if self.heading_stack else None
        n = len(self.doc.headings) + 1
        heading = Heading(
            section_id=f"{self.doc.doc_id}#s{n}",
            level=level,
            parent_id=parent.section_id if parent else "",
            title=line.text,
            breadcrumb=(parent.breadcrumb + " › " + line.text) if parent else line.text,
            start_line=line.line_num,
            end_line=line.line_num,  # fixed in close_sections
            anchor_id=self.anchor,
        )
        self.doc.headings.append(heading)
        self.heading_stack.append(heading)
        self.section_id = heading.section_id

    def close_sections(self) -> None:
        """end_line = the next peer-or-ancestor heading's start − 1, or the page's last line."""
        last = self.doc.lines[-1].line_num if self.doc.lines else 0
        hs = self.doc.headings
        for i, h in enumerate(hs):
            h.end_line = last
            for nxt in hs[i + 1 :]:
                if nxt.level <= h.level:
                    h.end_line = nxt.start_line - 1
                    break

    # ----- the walk -----

    def walk(self, node: Tag) -> None:
        run: list = []
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                run.append(child)
                continue
            if not isinstance(child, Tag) or child.name in SKIP_TAGS:
                continue
            if child.name in BLOCK_TAGS:
                if run:
                    self.emit(node, run)
                    run = []
                # Anchors come from block-level ids only: a counter badge's id is not a place.
                if child.get("id"):
                    self.anchor = child["id"]
                if child.name == "table":
                    self.walk_table(child)
                else:
                    self.walk(child)
            else:
                run.append(child)
        if run:
            self.emit(node, run)

    def walk_table(self, table: Tag) -> None:
        self.doc.n_tables += 1
        table_id = f"{self.doc.doc_id}#t{self.doc.n_tables}"
        headers: list[str] = []
        for child in table.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "caption":
                self.walk(child)
            elif child.name in ("thead", "tbody", "tfoot"):
                for tr in child.find_all("tr", recursive=False):
                    headers = self.walk_row(tr, table_id, headers)
            elif child.name == "tr":
                headers = self.walk_row(child, table_id, headers)

    def walk_row(self, tr: Tag, table_id: str, headers: list[str]) -> list[str]:
        cells = [c for c in tr.children if isinstance(c, Tag) and c.name in ("td", "th")]
        texts: list[str] = []
        first = last = 0
        for cell in cells:
            before = self.n
            self.walk(cell)
            texts.append(squash(inline_text(cell)))
            if self.n > before:
                first = first or before + 1
                last = self.n
        if not cells:
            return headers
        if all(c.name == "th" for c in cells) and not headers:
            return texts  # the header row names the columns; it is not a body row
        cols = headers or [f"col{i + 1}" for i in range(len(texts))]
        pairs = [f"{cols[i] if i < len(cols) else f'col{i + 1}'}: {v}" for i, v in enumerate(texts)]
        self.doc.rows.append(
            TableRow(
                table_id=table_id,
                line_num=first or self.n,
                line_end=last or self.n,
                column_headers=list(cols),
                row_cells=texts,
                row_serialized=" | ".join(pairs),
            )
        )
        return headers


_TITLE_RE = re.compile(r"\s+")


def parse_html(doc_id: str, html: str) -> ParsedDocument:
    """Parse one HTML document (or fragment) into lines, headings, rows and links."""
    soup = BeautifulSoup(html, "lxml")
    html_tag = soup.find("html")
    lang_attr = (html_tag.get("lang") or "") if html_tag else ""
    title_tag = soup.find("title")
    title = squash(title_tag.get_text()) if title_tag else ""
    doc = ParsedDocument(doc_id=doc_id, title=title, lang_attr=lang_attr)
    root = soup.body or soup
    walker = _Walker(doc)
    walker.walk(root)
    walker.close_sections()
    if not doc.title:
        first = next((h for h in doc.headings if h.level == 1), None) or (doc.headings[0] if doc.headings else None)
        doc.title = first.title if first else doc_id
    return doc
