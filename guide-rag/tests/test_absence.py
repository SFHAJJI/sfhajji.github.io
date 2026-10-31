""""Not in this guide": the justification with its four kinds of evidence and its reason."""

from test_retrieval_fixtures import DICTIONARY, expand, kw, make_tables, plan_for, pq, q_permis

from guide_rag.generation.absence import build_absence, coverage_of, innermost_title
from guide_rag.generation.schemas import AbsenceJustification
from guide_rag.retrieval.result import retrieve
from guide_rag.retrieval.scope import section_bounds


def absence_for(q, tables=None):
    t = tables or make_tables()
    r = retrieve(q, plan_for(q), t, DICTIONARY)
    assert r.not_found
    return build_absence(q, r, t, DICTIONARY, index_version="idx-test-1", pipeline_version="guide-rag/0.1")


def test_concept_not_found_carries_the_four_kinds_of_evidence():
    a = absence_for(q_permis())
    assert isinstance(a, AbsenceJustification) and a.answer is None and a.reason == "concept_not_found"
    # 1. the concepts searched, with every variant and zero hits
    assert [(c.concept, c.line_hits, c.pages_with_hits) for c in a.searched_concepts] == [("echanger", 0, []), ("permis", 0, [])]
    assert "driving licence" in a.searched_concepts[1].variants
    # 2. the closest mentions (none here) 3. the coverage 4. the suggestion
    assert a.closest_mentions == []
    assert a.parse_coverage.pages_total == 2 and a.parse_coverage.lines_total == 27 and a.parse_coverage.index_version == "idx-test-1"
    assert a.suggestion == "The guide never mentions echanger, permis; try another wording or another topic of the guide."
    assert not a.answer_found and not a.complete_answer_found


def test_concept_found_but_off_topic_with_why_not_sentences():
    q = pq("Quel est le loyer ?", [kw("loyer", concept="loyer"), *expand("loyer")])
    a = absence_for(q)
    assert a.reason == "concept_found_but_off_topic"
    assert a.searched_concepts[0].pages_with_hits == ["logement"] and a.searched_concepts[0].line_hits == 3
    why = {m.line_num: m.why_not_an_answer for m in a.closest_mentions}
    assert why[5] == "names loyer in the 'Bail' section, which is about bail"
    assert why[10] == "names loyer in the 'Garantie locative' section, which is about garantie locative"
    assert all(m.doc_id == "logement" and m.snippet for m in a.closest_mentions)
    assert "sections about something else" in a.suggestion


def test_ambiguous_question_takes_the_proposed_default():
    q = pq("et ça ?", [kw("ça")], ambiguity_reason="pronoun_only", suggested_clarification="Vous voulez dire le bail ou la garantie locative ?",
           proposed_default="bail", candidate_values=["bail", "garantie_locative"])
    a = absence_for(q)
    assert a.reason == "ambiguous_question" and a.suggestion == "bail"
    assert a.suggested_clarification == "Vous voulez dire le bail ou la garantie locative ?"


def test_coverage_is_computed_from_the_tables_when_none_was_saved():
    t = make_tables()
    t.parse_coverage = None
    c = coverage_of(t, "v1", "p1")
    assert c.model_dump(exclude={"fetched_at"}) == {"pages_total": 2, "pages_with_text": 2, "lines_total": 27, "sections_total": 7,
                                                     "tables_total": 1, "cross_refs": 0, "index_version": "v1", "pipeline_version": "p1"}


def test_innermost_title_picks_the_deepest_section():
    b = section_bounds(make_tables().toc_df)
    assert innermost_title(b, "logement", 10) == "Garantie locative"
    assert innermost_title(b, "logement", 2) == "Logement"
    assert innermost_title(b, "nowhere", 1) == ""


def test_mention_from_a_discarded_candidate_when_no_page_was_kept():
    # No summary line names the terms, so level 0 keeps nothing and the detectors read every page: the
    # one hit sits in a section about another concept, so it is discarded and becomes a mention.
    q = pq("assurance ?", [kw("assurance"), kw("permis", concept="permis")])
    a = absence_for(q)
    assert a.reason == "concept_not_found"
    assert [(m.doc_id, m.line_num) for m in a.closest_mentions] == [("voiture", 7)]
    assert a.closest_mentions[0].why_not_an_answer == "names assurance in the 'Immatriculation' section, which is about immatriculation"
    assert a.suggestion.startswith("The guide never mentions permis; it does cover assurance")
