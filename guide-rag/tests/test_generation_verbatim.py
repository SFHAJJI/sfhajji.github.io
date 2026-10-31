"""The no-model generator: typed items, the listing shape, the two booleans, conflicts, caveats."""

import pandas as pd
from test_retrieval_fixtures import (DICTIONARY, kw, make_tables, plan_for, pq, q_bail, q_edl_date, q_garantie, q_immat_list,
                                     q_permis)

from guide_rag.generation.schemas import AmountAnswer, DateAnswer, ListAnswer, TextAnswer
from guide_rag.generation.verbatim import generate_verbatim
from guide_rag.retrieval.result import retrieve


def gen(q, tables=None):
    t = tables or make_tables()
    return generate_verbatim(q, retrieve(q, plan_for(q), t, DICTIONARY), t)


def test_amount_is_typed_from_the_capture_with_the_line_as_span():
    a = gen(q_garantie())
    assert isinstance(a, AmountAnswer) and a.extraction_method == "computed"
    assert [(i.amount.value, i.amount.currency, i.amount.unit) for i in a.items] == [(2.0, None, "mois de loyer"), (1500.0, "EUR", None), (750.0, "EUR", None)]
    span = a.items[0].spans[0]
    assert (span.doc_id, span.line_start, span.line_end) == ("logement", 10, 10)
    assert span.quote == "Elle correspond en général à deux mois de loyer, soit 1 500 € pour un loyer de 750 €."
    assert a.answer_found and a.complete_answer_found and a.confidence == 1.0


def test_date_is_typed_iso_with_original():
    a = gen(q_edl_date())
    assert isinstance(a, DateAnswer) and a.items[0].date.model_dump() == {"iso": "2025-01-15", "original": "15 janvier 2025"}
    assert a.items[0].spans[0].line_start == 14 and a.keywords_found == ["signé", "état des lieux"]


def test_text_answer_is_the_anchor_lines_verbatim():
    a = gen(q_bail())
    assert isinstance(a, TextAnswer) and a.extraction_method == "verbatim" and len(a.items) == 1
    item = a.items[0]
    assert item.spans[0].model_dump() == {"doc_id": "logement", "line_start": 4, "line_end": 6, "quote": item.text}
    assert item.text.startswith("Le bail est le contrat de location")
    assert a.complete_answer_found  # the paragraph context covers the whole Bail section
    assert a.context_structured[0].breadcrumb == "Logement › Bail" and a.context_structured[0].url_anchor.endswith("#bail")


def test_listing_gives_one_item_per_matching_line_or_list_item():
    a = gen(q_immat_list())
    assert isinstance(a, ListAnswer) and a.extraction_method == "verbatim"
    assert [i.spans[0].line_start for i in a.items] == [4, 5, 6, 7]
    assert a.items[2].text == "Certificat de conformité" and a.items[2].spans[0].quote == "Certificat de conformité"
    assert a.complete_answer_found  # the context is the whole section


def test_the_two_booleans_and_caveat_on_a_partial_context():
    q = pq("Qu'est-ce que le bail ?", [kw("bail", concept="bail")], answer_context="line")
    a = gen(q)
    assert a.answer_found and not a.complete_answer_found
    assert a.caveats == ["The context covers lines 4-6 of 'Logement › Bail' (the section spans lines 3-7), not the whole section."]


def test_boolean_answer_is_inferred_with_a_caveat():
    q = pq("Le contrôle technique est-il obligatoire ?", [kw("contrôle technique", concept="controle_technique"), kw("obligatoire")], answer_type="boolean")
    a = gen(q)
    assert a.kind == "boolean" and a.items[0].boolean is True and a.extraction_method == "inferred"
    assert a.items[0].spans[0].line_start == 9 and "negation heuristic" in a.caveats[0]


def test_not_answered_when_no_primary():
    a = gen(q_permis())
    assert isinstance(a, TextAnswer) and a.items == [] and not a.answer_found and not a.complete_answer_found
    assert a.extraction_method == "na" and a.caveats[0].startswith("No keyword of the question")


def _tables_with_a_conflicting_page():
    t = make_tables()
    extra = [
        {"doc_id": "colocation", "line_num": 1, "text": "Colocation", "element": "h1", "section_id": "colocation#s1", "anchor_id": "top", "css_path": "h1", "char_count": 10, "is_heading": True},
        {"doc_id": "colocation", "line_num": 2, "text": "Garantie locative", "element": "h2", "section_id": "colocation#s2", "anchor_id": "g", "css_path": "h2", "char_count": 17, "is_heading": True},
        {"doc_id": "colocation", "line_num": 3, "text": "En colocation la garantie locative est de 1 000 € par personne.", "element": "p", "section_id": "colocation#s2", "anchor_id": "g", "css_path": "p", "char_count": 60, "is_heading": False},
    ]
    t.line_df = pd.concat([t.line_df, pd.DataFrame(extra)], ignore_index=True)
    t.toc_df = pd.concat([t.toc_df, pd.DataFrame([
        {"doc_id": "colocation", "section_id": "colocation#s1", "level": 1, "parent_id": None, "title": "Colocation", "breadcrumb": "Colocation", "start_line": 1, "end_line": 3, "anchor_id": "top", "source": "headings"},
        {"doc_id": "colocation", "section_id": "colocation#s2", "level": 2, "parent_id": "colocation#s1", "title": "Garantie locative", "breadcrumb": "Colocation › Garantie locative", "start_line": 2, "end_line": 3, "anchor_id": "g", "source": "headings"},
    ])], ignore_index=True)
    t.corpus_index = pd.concat([t.corpus_index, pd.DataFrame([{
        "doc_id": "colocation", "url": "https://example.org/colocation", "title": "Colocation", "topic": "housing",
        "summary_line": "Colocation — Partager un logement. Garantie locative.", "tags": ["logement", "garantie_locative"], "n_lines": 3, "lang": "fr"}])], ignore_index=True)
    return t


def test_conflicting_evidence_between_two_pages():
    t = _tables_with_a_conflicting_page()
    q = q_garantie()
    r = retrieve(q, plan_for(q), t, DICTIONARY)
    assert {c.anchor.doc_id for c in r.primaries} == {"logement", "colocation"}
    a = generate_verbatim(q, r, t)
    assert len(a.conflicting_evidence) == 1
    ce = a.conflicting_evidence[0]
    assert set(ce.candidate_ids) == {"logement#l9-l10", "colocation#l3-l3"} and "1000 EUR" in " ".join(ce.values)
    assert any("Conflicting value" in c for c in a.caveats)


def test_keywords_found_lists_the_primaries_keywords():
    a = gen(q_garantie())
    assert a.keywords_found == ["garantie", "garantie locative"]
