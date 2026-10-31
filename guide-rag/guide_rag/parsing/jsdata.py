"""Tolerant extraction of data literals from JavaScript source, without executing it.

The site keeps its content in data scripts (``window.KB = {...}``, ``window.FICHES.x = {...}``,
``var ENTREES = [...]``). Those are object literals, not programs: a small recursive-descent
reader is enough, and it never runs anything. It accepts what a hand-written data file uses
(comments, unquoted keys, single or double quotes, trailing commas, ``"a" + "b"`` string
concatenation, references to other names) and refuses the rest with a clear error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class JsLiteralError(ValueError):
    """The text at this position is not a data literal we read."""


@dataclass(frozen=True)
class JsRef:
    """A bare name found where a value was expected (``ACD``, ``window.FICHES.vehicule``).

    Resolved later against the other literals of the same site; kept as a value until then.
    """

    name: str


_IDENT = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*")
_NUMBER = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_KEYWORDS = {"true": True, "false": False, "null": None, "undefined": None}
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def _skip_ws(text: str, pos: int) -> int:
    """Skip whitespace and both comment forms."""
    n = len(text)
    while pos < n:
        c = text[pos]
        if c.isspace():
            pos += 1
        elif text.startswith("//", pos):
            end = text.find("\n", pos)
            pos = n if end < 0 else end + 1
        elif text.startswith("/*", pos):
            end = text.find("*/", pos + 2)
            if end < 0:
                raise JsLiteralError(f"unterminated comment at {pos}")
            pos = end + 2
        else:
            break
    return pos


def _read_string(text: str, pos: int) -> tuple[str, int]:
    quote = text[pos]
    pos += 1
    out: list[str] = []
    n = len(text)
    while pos < n:
        c = text[pos]
        if c == quote:
            return "".join(out), pos + 1
        if c == "\\":
            pos += 1
            if pos >= n:
                break
            e = text[pos]
            if e == "u" and pos + 4 < n:
                out.append(chr(int(text[pos + 1 : pos + 5], 16)))
                pos += 5
                continue
            if e == "x" and pos + 2 < n:
                out.append(chr(int(text[pos + 1 : pos + 3], 16)))
                pos += 3
                continue
            if e == "\n":  # line continuation
                pos += 1
                continue
            out.append(_ESCAPES.get(e, e))
            pos += 1
            continue
        if c == "\n" and quote != "`":
            raise JsLiteralError(f"newline inside string at {pos}")
        out.append(c)
        pos += 1
    raise JsLiteralError(f"unterminated string starting at {pos}")


def parse_literal(text: str, pos: int = 0) -> tuple[Any, int]:
    """Read one literal at ``pos``; return ``(value, end_pos)``.

    Objects become dicts (insertion order kept), arrays lists, strings str, numbers int or
    float, ``true/false/null/undefined`` their Python counterparts, bare names ``JsRef``.
    """
    pos = _skip_ws(text, pos)
    if pos >= len(text):
        raise JsLiteralError("unexpected end of text")
    c = text[pos]

    if c == "{":
        obj: dict[str, Any] = {}
        pos += 1
        while True:
            pos = _skip_ws(text, pos)
            if text.startswith("}", pos):
                return obj, pos + 1
            # Keys: bare identifiers, quoted strings or numbers, as in any hand-written file.
            if text[pos] in "\"'":
                key, pos = _read_string(text, pos)
            else:
                m = _IDENT.match(text, pos) or _NUMBER.match(text, pos)
                if not m:
                    raise JsLiteralError(f"object key expected at {pos}")
                key, pos = m.group(0), m.end()
            pos = _skip_ws(text, pos)
            if not text.startswith(":", pos):
                raise JsLiteralError(f"':' expected after key {key!r} at {pos}")
            value, pos = parse_literal(text, pos + 1)
            obj[key] = value
            pos = _skip_ws(text, pos)
            if text.startswith(",", pos):
                pos += 1
                continue
            if text.startswith("}", pos):
                return obj, pos + 1
            raise JsLiteralError(f"',' or '}}' expected at {pos}")

    if c == "[":
        arr: list[Any] = []
        pos += 1
        while True:
            pos = _skip_ws(text, pos)
            if text.startswith("]", pos):
                return arr, pos + 1
            value, pos = parse_literal(text, pos)
            arr.append(value)
            pos = _skip_ws(text, pos)
            if text.startswith(",", pos):
                pos += 1
                continue
            if text.startswith("]", pos):
                return arr, pos + 1
            raise JsLiteralError(f"',' or ']' expected at {pos}")

    if c in "\"'`":
        value, pos = _read_string(text, pos)
        # "a" + "b" over several lines is how long paragraphs are written in these files.
        while True:
            look = _skip_ws(text, pos)
            if not text.startswith("+", look):
                break
            more, pos = parse_literal(text, look + 1)
            if not isinstance(more, str):
                raise JsLiteralError(f"only strings are concatenated, at {look}")
            value += more
        return value, pos

    m = _NUMBER.match(text, pos)
    if m and (c.isdigit() or c in "-."):
        s = m.group(0)
        return (float(s) if any(ch in s for ch in ".eE") else int(s)), m.end()

    m = _IDENT.match(text, pos)
    if m:
        name = m.group(0)
        end = m.end()
        if text.startswith("(", _skip_ws(text, end)):
            raise JsLiteralError(f"function call {name!r} at {pos}: not a data literal")
        if name in _KEYWORDS:
            return _KEYWORDS[name], end
        return JsRef(name), end

    raise JsLiteralError(f"unexpected character {c!r} at {pos}")


def extract_assignment(text: str, lhs: str) -> Any:
    """Return the literal assigned to ``lhs`` (``window.KB``, ``var TABLE``) in ``text``.

    The first assignment wins. Raises ``JsLiteralError`` when there is none or it is not a
    literal.
    """
    pattern = re.compile(r"(?<![\w.$])" + re.escape(lhs) + r"\s*=\s*(?!=)")
    m = pattern.search(text)
    if not m:
        raise JsLiteralError(f"no assignment to {lhs!r}")
    value, _ = parse_literal(text, m.end())
    return value


def find_assignments(text: str) -> dict[str, Any]:
    """Every ``var NAME =``, ``const/let NAME =`` and ``window.NAME[.NAME] =`` literal in ``text``.

    Assignments whose right-hand side is code (a function, a call) are skipped: data only.
    """
    found: dict[str, Any] = {}
    pattern = re.compile(
        r"(?:^|[;\s{(])(?:(?:var|const|let)\s+([A-Za-z_$][\w$]*)|(window(?:\.[A-Za-z_$][\w$]*)+))\s*=\s*(?!=)"
    )
    for m in pattern.finditer(text):
        name = m.group(1) or m.group(2)
        try:
            value, _ = parse_literal(text, m.end())
        except JsLiteralError:
            continue
        if isinstance(value, JsRef):
            continue
        found.setdefault(name, value)
    return found


def resolve(value: Any, env: dict[str, Any]) -> Any:
    """Replace every ``JsRef`` inside ``value`` by ``env[name]`` (or its last segment).

    An unknown reference becomes ``None``: the record keeps its shape and the gap is visible.
    """
    if isinstance(value, JsRef):
        if value.name in env:
            return resolve(env[value.name], env)
        # ``FICHES.vehicule`` names ``window.FICHES.vehicule``: match on the dotted suffix.
        suffix = [k for k in sorted(env) if k.endswith("." + value.name)]
        if len(suffix) == 1:
            return resolve(env[suffix[0]], env)
        short = value.name.rsplit(".", 1)[-1]
        if short in env:
            return resolve(env[short], env)
        return None
    if isinstance(value, dict):
        return {k: resolve(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, env) for v in value]
    return value
