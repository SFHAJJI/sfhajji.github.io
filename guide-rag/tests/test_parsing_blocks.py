"""The block parser: lines in reading order, headings nested, tables → rows, anchors, entities."""

from dataclasses import asdict

from guide_rag.parsing.blocks import css_path, fold, parse_html, squash
from tests.conftest import HOME_HTML


def _accueil():
    from bs4 import BeautifulSoup

    panel = BeautifulSoup(HOME_HTML, "lxml").find(id="panel-accueil")
    return parse_html("accueil", f'<html lang="fr"><body><main>{panel}</main></body></html>')


def test_reading_order_elements_and_numbering():
    doc = _accueil()
    texts = [ln.text for ln in doc.lines]
    assert texts[0] == "Vivre ici"
    assert [ln.line_num for ln in doc.lines] == list(range(1, len(doc.lines) + 1))
    assert [ln.element for ln in doc.lines[:3]] == ["h1", "p", "h2"]
    # the table comes after the lists, before the "Voiture" heading: document order
    i_caption = texts.index("Loyers moyens")
    assert texts.index("ou en espèces") < i_caption < texts.index("Voiture")


def test_entities_decoded_and_whitespace_squashed():
    doc = _accueil()
    lead = doc.lines[1].text
    assert lead.startswith("Un guide : démarches, logement & voiture.")
    assert "\n" not in lead and "  " not in lead
    assert doc.lines[1].char_count == len(lead)


def test_heading_nesting_parent_and_breadcrumb():
    doc = _accueil()
    by_title = {h.title: h for h in doc.headings}
    assert by_title["Logement"].parent_id == by_title["Vivre ici"].section_id
    assert by_title["Bail"].parent_id == by_title["Logement"].section_id
    assert by_title["Bail"].breadcrumb == "Vivre ici › Logement › Bail"
    assert by_title["Voiture"].level == 2 and by_title["Voiture"].parent_id == by_title["Vivre ici"].section_id
    assert [h.section_id for h in doc.headings] == [f"accueil#s{i}" for i in range(1, len(doc.headings) + 1)]


def test_end_line_is_next_peer_or_ancestor_minus_one_or_last_line():
    doc = _accueil()
    by_title = {h.title: h for h in doc.headings}
    last = doc.lines[-1].line_num
    assert by_title["Vivre ici"].end_line == last
    assert by_title["Logement"].end_line == by_title["Voiture"].start_line - 1
    assert by_title["Bail"].end_line == by_title["Prix"].start_line - 1
    assert by_title["Prix"].end_line == by_title["Voiture"].start_line - 1  # ancestor-level peer closes the h3
    assert by_title["Voiture"].end_line == last
    for h in doc.headings:
        assert h.end_line >= h.start_line


def test_lines_belong_to_innermost_section():
    doc = _accueil()
    by_title = {h.title: h for h in doc.headings}
    bail_lines = [ln for ln in doc.lines if ln.section_id == by_title["Bail"].section_id]
    assert [ln.text for ln in bail_lines] == ["Bail", "Un bail écrit", "Une garantie", "bancaire", "ou en espèces"]


def test_nested_list_keeps_the_parent_items_own_text():
    doc = _accueil()
    texts = [ln.text for ln in doc.lines]
    assert "Une garantie" in texts and "bancaire" in texts
    assert all(ln.element == "li" for ln in doc.lines if ln.text in ("Une garantie", "bancaire", "ou en espèces"))


def test_table_becomes_rows_and_cells_become_lines():
    doc = _accueil()
    assert doc.n_tables == 1
    assert [r.row_cells for r in doc.rows] == [["Luxembourg", "2 000 €"], ["Esch", "1 500 €"]]
    assert doc.rows[0].column_headers == ["Ville", "Loyer"]
    assert doc.rows[0].row_serialized == "Ville: Luxembourg | Loyer: 2 000 €"
    assert doc.rows[0].table_id == "accueil#t1"
    cells = {ln.line_num: ln for ln in doc.lines}
    assert cells[doc.rows[0].line_num].text == "Luxembourg" and cells[doc.rows[0].line_end].text == "2 000 €"
    assert {ln.element for ln in doc.lines if ln.text in ("Ville", "Loyer")} == {"th"}
    assert next(ln for ln in doc.lines if ln.text == "Loyers moyens").element == "caption"


def test_table_without_thead_uses_its_first_all_th_row_as_headers():
    doc = parse_html("t", "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>")
    assert len(doc.rows) == 1 and doc.rows[0].column_headers == ["A", "B"] and doc.rows[0].row_cells == ["1", "2"]


def test_anchor_is_nearest_preceding_block_id():
    doc = _accueil()
    by_text = {ln.text: ln for ln in doc.lines}
    assert by_text["Vivre ici"].anchor_id == "panel-accueil"
    assert by_text["Logement"].anchor_id == "logement"
    assert by_text["Un bail écrit"].anchor_id == "logement"
    assert by_text["Voiture"].anchor_id == "voiture"
    # an inline id (the badge span) is not a place
    assert by_text["Trouver un logement prend du temps. 3 Voir le bail."].anchor_id == "logement"


def test_scripts_buttons_and_form_controls_are_not_lines():
    doc = _accueil()
    texts = " ".join(ln.text for ln in doc.lines)
    assert "var x" not in texts and "Fermer" not in texts and "Chercher" not in texts and "Question" not in texts
    assert "Attention. Les délais changent." in texts


def test_css_path_starts_at_nearest_id():
    doc = _accueil()
    by_text = {ln.text: ln for ln in doc.lines}
    assert by_text["Vivre ici"].css_path == "section#panel-accueil > h1"
    # two <div> siblings under the section (table-wrap, notice): the position disambiguates
    assert by_text["Luxembourg"].css_path == "section#panel-accueil > div.table-wrap:nth-of-type(1) > table > tbody > tr:nth-of-type(1) > td:nth-of-type(1)"


def test_links_carry_line_and_context():
    doc = _accueil()
    hrefs = {l.href: l for l in doc.links}
    assert set(hrefs) == {"second/", "https://example.org/ext", "#fiche/bail", "#voiture"}
    assert hrefs["#fiche/bail"].text == "le bail" and "Voir le bail" in hrefs["#fiche/bail"].context


def test_title_and_lang_from_document_or_first_h1():
    doc = parse_html("x", "<html lang='de'><head><title>Titel  hier</title></head><body><h1>H</h1></body></html>")
    assert doc.title == "Titel hier" and doc.lang_attr == "de"
    assert parse_html("y", "<body><p>intro</p><h1>First</h1></body>").title == "First"


def test_lines_before_the_first_heading_have_no_section():
    doc = parse_html("y", "<body><p>intro</p><h1>First</h1><p>body</p></body>")
    assert [ln.section_id for ln in doc.lines] == ["", "y#s1", "y#s1"]


def test_parse_is_idempotent():
    a, b = _accueil(), _accueil()
    assert [asdict(x) for x in a.lines] == [asdict(x) for x in b.lines]
    assert [asdict(x) for x in a.headings] == [asdict(x) for x in b.headings]
    assert [asdict(x) for x in a.rows] == [asdict(x) for x in b.rows]


def test_helpers():
    assert squash("  a  b\n\tc ") == "a b c"
    assert fold("Été à Esch-sur-Alzette") == "ete a esch-sur-alzette"
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<div id='r'><p>a</p><p>b</p></div>", "lxml")
    assert css_path(soup.find_all("p")[1]) == "div#r > p:nth-of-type(2)"
