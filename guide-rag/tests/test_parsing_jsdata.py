"""The tolerant JS literal reader: data in, no execution."""

import pytest

from guide_rag.parsing.jsdata import JsLiteralError, JsRef, extract_assignment, find_assignments, parse_literal, resolve


def test_objects_arrays_scalars_and_trailing_commas():
    value, end = parse_literal("""{ a: 1, "b": 'two', c: [true, false, null, undefined, -2.5, 1e3,], d: { e: {} }, }""")
    assert value == {"a": 1, "b": "two", "c": [True, False, None, None, -2.5, 1000.0], "d": {"e": {}}}
    assert isinstance(value["a"], int) and isinstance(value["c"][5], float)


def test_comments_everywhere():
    text = """{ // line comment
      a: /* inline */ 1, /* multi
      line */ b: [ // another
        2 ] }"""
    assert parse_literal(text)[0] == {"a": 1, "b": [2]}


def test_string_escapes_and_concatenation():
    value, _ = parse_literal(r'''"l\'été é \"q\" \n" + 'suite ' +
        "fin"''')
    assert value == "l'été é \"q\" \nsuite fin"


def test_references_and_resolve():
    value, _ = parse_literal("[ACD, window.FICHES.vehicule, {x: GUI}]")
    assert value[0] == JsRef("ACD") and value[1] == JsRef("window.FICHES.vehicule")
    env = {"ACD": {"t": "acd"}, "window.FICHES.vehicule": {"id": "vehicule"}, "GUI": "g"}
    assert resolve(value, env) == [{"t": "acd"}, {"id": "vehicule"}, {"x": "g"}]
    assert resolve([JsRef("FICHES.vehicule"), JsRef("unknown")], env) == [{"id": "vehicule"}, None]


def test_function_calls_and_code_are_refused():
    with pytest.raises(JsLiteralError):
        parse_literal("{ a: eur(3) }")
    with pytest.raises(JsLiteralError):
        parse_literal("function () {}")
    with pytest.raises(JsLiteralError):
        parse_literal("{ a: 1 b: 2 }")
    with pytest.raises(JsLiteralError):
        parse_literal('"unterminated')


def test_extract_assignment_and_find_assignments(tiny_kb_js):
    kb = extract_assignment(tiny_kb_js, "window.KB")
    assert [f["id"] for f in kb["fiches"]] == ["bail", "voiture"]
    assert kb["fiches"][0]["corps"][0] == "Un bail écrit est la règle. Il fixe le loyer."
    assert kb["fiches"][0]["corps"][1] == {"h": "La garantie locative"}
    assert kb["fiches"][0]["corps"][2] == "Elle vaut au plus trois mois de loyer, dit l'article."
    found = find_assignments(tiny_kb_js + "\nvar T = window.KB.meta;\nvar f = function () {};\nvar n = 3;")
    assert set(found) == {"window.KB", "n"}  # references and functions are skipped
    with pytest.raises(JsLiteralError):
        extract_assignment(tiny_kb_js, "window.NOPE")
    assert extract_assignment("x == 1; var y = [1]", "var y") == [1]
