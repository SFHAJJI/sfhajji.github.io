"""The tables of SPEC §1 built from the tiny site: documents, cross refs, index, determinism."""

import json

from guide_rag.parsing.documents import build_documents
from guide_rag.parsing.tables import TABLE_NAMES, build_tables, dumps, index_version, to_records
from tests.conftest import SITE


def test_documents_follow_the_site_model(tiny_documents):
    docs, data = tiny_documents
    assert [d.doc_id for d in docs] == ["accueil", "fiches", "bail", "voiture", "faq", "second"]
    by_id = {d.doc_id: d for d in docs}
    assert by_id["bail"].url == SITE + "#fiche/bail" and by_id["bail"].kind == "fiche"
    assert by_id["faq"].url == SITE + "#faq" and by_id["second"].url == SITE + "second/"
    assert by_id["bail"].parsing_method == "js_data+html_blocks/1" and by_id["accueil"].parsing_method == "html_blocks/1"
    assert by_id["bail"].raw_files == ["index.html", "app_kb.js"] and by_id["bail"].reader_words == ["bail", "caution", "loyer"]
    assert any("window.KB with 2 fiches, 2 faq, 1 timeline phases" in n for n in data.notes)


def test_page_df(tiny_tables):
    page = tiny_tables["page_df"].set_index("doc_id")
    assert page.loc["bail", "title"] == "Signer un bail" and page.loc["bail", "lang"] == "fr"
    assert page.loc["second", "lang"] == "en" and page.loc["second", "n_tables"] == 1
    assert page.loc["bail", "n_tables"] == 1 and page.loc["bail", "n_sections"] == 5  # h1, h2, h3 table, À retenir, Sources
    assert page.loc["accueil", "n_lines"] == (tiny_tables["line_df"]["doc_id"] == "accueil").sum()
    assert set(page["parsing_method"]) == {"html_blocks/1", "js_data+html_blocks/1"}


def test_fiche_rendering_gives_verbatim_lines_and_sections(tiny_tables):
    lines = tiny_tables["line_df"]
    bail = lines[lines["doc_id"] == "bail"]
    texts = list(bail["text"])
    assert texts[:3] == ["Signer un bail", "Le bail se signe avant les clés.", "Un bail écrit est la règle. Il fixe le loyer."]
    assert "Elle vaut au plus trois mois de loyer, dit l'article." in texts
    toc = tiny_tables["toc_df"]
    bail_toc = toc[toc["doc_id"] == "bail"]
    assert list(bail_toc["title"]) == ["Signer un bail", "La garantie locative", "Délais", "À retenir", "Sources officielles"]
    assert list(bail_toc["level"]) == [1, 2, 3, 2, 2]
    rows = tiny_tables["row_df"]
    assert list(rows[rows["doc_id"] == "bail"]["row_serialized"]) == ["Étape: Préavis | Délai: 3 mois", "Étape: État des lieux | Délai: à la remise"]


def test_faq_questions_are_headings_linking_their_fiche(tiny_tables):
    toc = tiny_tables["toc_df"]
    faq = toc[toc["doc_id"] == "faq"]
    assert "Combien de mois de garantie ?" in list(faq["title"]) and "Logement" in list(faq["title"])
    refs = tiny_tables["cross_ref_df"]
    assert set(refs[refs["doc_id"] == "faq"]["target_doc_id"]) == {"bail", "voiture"}


def test_cross_refs_resolve_internal_links_only(tiny_tables):
    refs = tiny_tables["cross_ref_df"]
    acc = refs[refs["doc_id"] == "accueil"].set_index("href")
    assert acc.loc["second/", "target_doc_id"] == "second"
    assert acc.loc["#fiche/bail", "target_doc_id"] == "bail" and acc.loc["#fiche/bail", "target_anchor"] == ""
    assert acc.loc["#voiture", "target_doc_id"] == "accueil" and acc.loc["#voiture", "target_anchor"] == "voiture"
    assert "https://example.org/ext" not in acc.index
    sec = refs[refs["doc_id"] == "second"].set_index("href")
    assert sec.loc["../#logement", "target_doc_id"] == "accueil" and sec.loc["../#logement", "target_anchor"] == "logement"
    assert sec.loc["../#fiche/voiture", "target_doc_id"] == "voiture"
    assert "back to housing" in sec.loc["../#logement", "context"]


def test_corpus_index_topic_tags_and_router_line(tiny_tables):
    ci = tiny_tables["corpus_index"].set_index("doc_id")
    assert ci.loc["bail", "topic"] == "housing" and ci.loc["voiture", "topic"] == "vehicle"
    assert "garantie locative" in ci.loc["bail", "tags"] and "immatriculation" in ci.loc["voiture", "tags"]
    line = ci.loc["bail", "summary_line"]
    assert line.startswith("Signer un bail. Mots du lecteur : bail, caution, loyer.")
    assert "Mots de la page : La garantie locative, Délais." in line and "Forme :" in line
    assert "À retenir" not in line  # boilerplate headings are not the page's vocabulary
    assert ci.loc["faq", "topic"] == "other"  # a page about everything is about nothing in particular


def test_coverage_counts_match_the_tables(tiny_tables, tiny_coverage):
    c = tiny_coverage
    assert c["pages_total"] == len(tiny_tables["page_df"]) == 6
    assert c["lines_total"] == len(tiny_tables["line_df"])
    assert c["sections_total"] == len(tiny_tables["toc_df"])
    assert c["cross_refs"] == len(tiny_tables["cross_ref_df"])
    assert c["tables_total"] == int(tiny_tables["page_df"]["n_tables"].sum()) == 3
    assert c["index_version"] == index_version(tiny_tables) and len(c["index_version"]) == 64
    assert c["pipeline_version"].startswith("guide-rag/")


def test_every_line_section_exists_and_ranges_hold(tiny_tables):
    toc = tiny_tables["toc_df"]
    sections = set(toc["section_id"])
    for s in tiny_tables["line_df"]["section_id"]:
        assert s == "" or s in sections
    assert (toc["end_line"] >= toc["start_line"]).all()
    last = tiny_tables["line_df"].groupby("doc_id")["line_num"].max()
    for _, h in toc.iterrows():
        assert h["end_line"] <= last[h["doc_id"]]


def test_same_raw_files_give_byte_identical_json(tiny_raw_dir, tiny_manifest):
    first = {n: dumps(to_records(t, n)) for n, t in build_tables(*build_documents(tiny_raw_dir, tiny_manifest), site_url=SITE).tables.items()}
    second = {n: dumps(to_records(t, n)) for n, t in build_tables(*build_documents(tiny_raw_dir, tiny_manifest), site_url=SITE).tables.items()}
    assert first == second
    assert set(first) == set(TABLE_NAMES)
    for name, text in first.items():
        assert json.loads(text) == to_records(build_tables(*build_documents(tiny_raw_dir, tiny_manifest), site_url=SITE).tables[name], name)


def test_index_version_changes_when_a_line_changes(tiny_tables):
    changed = {n: t.copy() for n, t in tiny_tables.items()}
    changed["line_df"].loc[0, "text"] = changed["line_df"].loc[0, "text"] + " !"
    assert index_version(changed) != index_version(tiny_tables)
