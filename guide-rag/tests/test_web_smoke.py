"""The page's static checks: the HTML references only files that exist, every JS import resolves,
nothing from the guide can reach innerHTML, and the JS engine mirrors the Python modules it ports
(one file per module, the same top-level function and class names), so a re-sync is a diff."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
INDEX_HTML = ROOT / "index.html"

# Python module -> its JS port. Helpers with no Python counterpart (_py.js, cli.js) are not listed.
PORTED = {
    "guide_rag/question/stopwords.py": "web/engine/stopwords.js",
    "guide_rag/question/normalize.py": "web/engine/normalize.js",
    "guide_rag/question/dictionary.py": "web/engine/dictionary.js",
    "guide_rag/question/parse_question.py": "web/engine/parse_question.js",
    "guide_rag/question/dispatcher.py": "web/engine/dispatcher.js",
    "guide_rag/retrieval/text.py": "web/engine/text.js",
    "guide_rag/retrieval/contracts.py": "web/engine/contracts.js",
    "guide_rag/retrieval/detectors.py": "web/engine/detectors.js",
    "guide_rag/retrieval/router.py": "web/engine/router.js",
    "guide_rag/retrieval/scope.py": "web/engine/scope.js",
    "guide_rag/retrieval/arbiter.py": "web/engine/arbiter.js",
    "guide_rag/retrieval/result.py": "web/engine/result.js",
    "guide_rag/retrieval/sweep.py": "web/engine/sweep.js",
    "guide_rag/generation/schemas.py": "web/engine/schemas.js",
    "guide_rag/generation/verbatim.py": "web/engine/verbatim.js",
    "guide_rag/generation/validator.py": "web/engine/validator.js",
    "guide_rag/generation/absence.py": "web/engine/absence.js",
    "guide_rag/generation/meta.py": "web/engine/meta.js",
    "guide_rag/generation/pipeline.py": "web/engine/pipeline.js",
    "guide_rag/generation/llm.py": "web/engine/llm.js",
}
# Python names that have no JS meaning (pydantic type aliases, module-level caches).
NOT_PORTED = {"Answer", "AnswerOrAbsence"}

FORBIDDEN = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write(", "document.writeln(")


def web_js_files() -> list[Path]:
    return sorted(p for p in WEB.rglob("*.js") if "node_modules" not in p.parts) + sorted(WEB.rglob("*.mjs"))


def test_root_index_html_exists_and_links_only_existing_files():
    assert INDEX_HTML.exists(), "the page lives at the repository root as index.html"
    html = INDEX_HTML.read_text(encoding="utf-8")
    refs = re.findall(r"""(?:src|href)=["']([^"']+)["']""", html)
    missing = []
    for ref in refs:
        if ref.startswith(("http://", "https://", "mailto:", "#", "data:", "//")):
            continue
        path = ROOT / ref.split("?")[0].split("#")[0]
        if not path.exists():
            missing.append(ref)
    assert not missing, f"index.html references files that do not exist: {missing}"
    assert 'src="web/app.js"' in html and 'type="module"' in html


def test_every_js_import_resolves():
    unresolved = []
    for path in web_js_files():
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"""(?:from|import)\s*\(?\s*["']([^"']+)["']""", text):
            if not target.startswith("."):
                if target.startswith("node:"):
                    continue
                unresolved.append((str(path.relative_to(ROOT)), target, "bare specifier"))
                continue
            if not (path.parent / target).resolve().exists():
                unresolved.append((str(path.relative_to(ROOT)), target, "missing"))
    assert not unresolved, f"unresolved imports: {unresolved}"


def test_no_innerhtml_anywhere_on_the_page():
    offenders = []
    for path in [INDEX_HTML] + web_js_files():
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            if token in text:
                offenders.append((str(path.relative_to(ROOT)), token))
    assert not offenders, f"guide text must be rendered with textContent, never injected as HTML: {offenders}"


def test_guide_text_goes_through_textcontent_helper():
    dom = (WEB / "ui" / "dom.js").read_text(encoding="utf-8")
    assert "createTextNode" in dom and "innerHTML" not in dom


def _py_top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names - NOT_PORTED


def _js_defined_names(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    names = set(re.findall(r"\b(?:function|class)\s+([A-Za-z_$][\w$]*)", text))
    for block in re.findall(r"export\s*\{([^}]*)\}", text):
        for part in block.split(","):
            part = part.strip()
            if part:
                names.add(part.split(" as ")[-1].strip())
    for const in re.findall(r"export\s+const\s+([A-Za-z_$][\w$]*)", text):
        names.add(const)
    return names


@pytest.mark.parametrize("py_rel, js_rel", sorted(PORTED.items()))
def test_js_engine_mirrors_python_module(py_rel: str, js_rel: str):
    py_path, js_path = ROOT / py_rel, ROOT / js_rel
    assert js_path.exists(), f"{js_rel} is missing: every ported Python module has one JS module of the same name"
    py_names = _py_top_level_names(py_path)
    js_names = _js_defined_names(js_path)
    missing = sorted(py_names - js_names)
    assert not missing, f"{js_rel} lacks the names {py_rel} defines at top level: {missing} (port them under the same name)"


def test_dictionary_json_is_built_from_the_yaml():
    sys.path.insert(0, str(WEB))
    try:
        import build_data  # noqa: WPS433  (web/build_data.py)
    finally:
        sys.path.pop(0)
    data = build_data.build()
    out = WEB / "data" / "dictionary.json"
    assert out.exists()
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    for name, digest in data["built_from"].items():
        assert on_disk["built_from"][name] == digest
        assert hashlib.sha256((ROOT / "dictionary" / name).read_bytes()).hexdigest() == digest
    assert on_disk["concepts"] and on_disk["keywords"] and on_disk["abbreviations"]


def test_page_has_the_first_screen_and_the_panels():
    html = INDEX_HTML.read_text(encoding="utf-8")
    for needle in (
        'id="question"', 'class="chip"', 'id="page-picker"', 'id="answer"', 'id="source"', 'id="scope-picker"',
        'id="trace"', 'id="copy-trace"', 'id="model"', 'id="tab-methode"', 'id="tab-index"', 'id="tab-evaluation"',
        "https://github.com/SFHAJJI/guide-rag", "prefers-color-scheme",
    ):
        assert needle in html or needle in (WEB / "styles.css").read_text(encoding="utf-8"), needle
    assert html.count('class="chip"') == 3
