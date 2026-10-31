"""`retrieve()` end to end: roles, reasons, ids, methods, audit, confidence, not_found, determinism."""

from test_retrieval_fixtures import (DICTIONARY, expand, kw, make_tables, plan_for, pq, q_bail, q_edl_date, q_garantie,
                                     q_immat_list, q_permis)

from guide_rag.retrieval.result import confidence_of, retrieve


def test_primary_candidate_id_methods_and_captures():
    q = q_garantie()
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    p = r.candidates[0]
    assert p.role == "primary" and p.candidate_id == "logement#l9-l10"
    assert p.anchor.model_dump() == {"doc_id": "logement", "line_start": 9, "line_end": 10, "section_id": "logement#s3"}
    assert p.context.model_dump() == {"doc_id": "logement", "line_start": 9, "line_end": 10, "section_id": "logement#s3"}
    assert p.methods == ["anchor_regex", "keyword_lines", "title_match"]
    assert [c["raw"] for c in p.captures] == ["deux mois de loyer", "1 500 €", "750 €"]
    assert p.breadcrumb == "Logement › Garantie locative" and p.url_anchor == "https://example.org/logement#garantie"
    assert r.methods_used == ["keyword_lines", "title_match", "anchor_regex", "row_match", "arbiter_rules", "sweep"]
    assert "embeddings" in r.methods_skipped and "keywords prove absence" in r.methods_skipped["embeddings"]
    assert r.methods_skipped["llm_arbiter"] == "no key configured"


def test_discarded_candidate_names_x_not_y():
    q = q_bail()
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    roles = {c.candidate_id: c.role for c in r.candidates}
    assert roles == {"logement#l4-l6": "primary", "logement#l11-l11": "discarded"}
    d = next(c for c in r.candidates if c.role == "discarded")
    assert d.reason.startswith("The section 'Garantie locative' names 'garantie locative', not 'bail'")
    assert r.methods_skipped["anchor_regex"] == "answer type text asks for no typed anchor"
    assert r.methods_skipped["row_match"] == "no amount/date and no column named"


def test_per_section_audit_rows():
    q = q_edl_date()
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    rows = {a.section_id: (a.keyword, a.toc, a.kept) for a in r.per_section_audit}
    assert rows == {"logement#s1": (".", ".", "."), "logement#s2": ("Y", ".", "."), "logement#s3": ("Y", ".", "."), "logement#s4": ("Y", "Y", "Y")}
    assert all(a.doc_id == "logement" for a in r.per_section_audit)


def test_not_found_when_nothing_hits_with_reason():
    q = q_permis()
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    assert r.not_found and r.candidates == [] and r.confidence == 0.0
    assert r.not_found_reason == "No keyword of the question (échanger, permis, permis de conduire, driving licence) hits any line of any page."
    assert len(r.per_section_audit) == 7  # every page audited when none was kept


def test_not_found_when_every_hit_is_discarded():
    q = pq("Quel est le loyer ?", [kw("loyer", concept="loyer"), *expand("loyer")])
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    assert r.not_found and {c.role for c in r.candidates} == {"discarded"}
    assert "2 discarded (a section naming another concept)" in r.not_found_reason


def test_confidence_is_share_and_margin():
    assert confidence_of(1.0, 4.0, 0.0) == 1.0
    assert confidence_of(0.5, 2.0, 0.0) == 0.65
    assert confidence_of(1.0, 4.0, 2.0) == 0.85
    assert confidence_of(1.0, 0.0, 0.0) == 0.0
    q = q_immat_list()  # "documents" is weak (0.3): coverage 1/1.3 = 0.769 and no rival -> 0.7 x 0.769 + 0.3
    assert retrieve(q, plan_for(q), make_tables(), DICTIONARY).confidence == 0.838


def test_current_page_boost_is_applied_and_logged():
    q = q_garantie(pages_hint=["logement"])
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    assert "current_page_boost" in r.methods_used and r.candidates[0].score == 5.772  # 4.44 x 1.3
    q2 = q_garantie()
    assert "current_page_boost" in retrieve(q2, plan_for(q2), make_tables(), DICTIONARY).methods_skipped


def test_route_and_sweep_are_in_the_result():
    q = q_garantie()
    r = retrieve(q, plan_for(q), make_tables(), DICTIONARY)
    assert [p.doc_id for p in r.route_pages] == ["logement"] and r.route_pages[0].reason.startswith("kept:")
    assert [s.section_id for s in r.route_sections] == ["logement#s3"]
    assert [(c.concept, c.line_hits) for c in r.sweep_concepts] == [("garantie_locative", 4)]


def test_duck_typed_inputs_are_accepted():
    parsed = {
        "question_id": "d1", "original_question": "Combien coûte la garantie locative ?", "corrected_question": "combien coute la garantie locative",
        "language": "fr", "answer_shape": "single", "answer_type": "amount",
        "keywords": [{"text": "garantie locative", "weight": 1.0, "source": "direct", "concept": "garantie_locative", "is_regex": False}],
        "structural_hints": {"pages_hint": None, "toc_section_hint": None, "answer_context": "line"},
        "decomposition": {"pattern": "single", "sub_questions": []},
    }
    plan = {"activations": {"use_toc": {"on": True, "reason": "3+ sections"}, "use_row_level": {"on": True, "reason": "amount"}}}
    r = retrieve(parsed, plan, make_tables(), DICTIONARY)
    assert r.candidates[0].role == "primary" and r.candidates[0].candidate_id == "logement#l9-l10"


def test_retrieve_is_deterministic():
    q = q_edl_date()
    a = retrieve(q, plan_for(q), make_tables(), DICTIONARY).model_dump_json()
    b = retrieve(q, plan_for(q), make_tables(), DICTIONARY).model_dump_json()
    assert a == b


def test_missing_optional_tables_do_not_break():
    t = make_tables()
    t.row_df = None
    t.corpus_index = None
    t.page_df = None
    q = q_garantie()
    r = retrieve(q, plan_for(q), t, DICTIONARY)
    assert r.candidates[0].role == "primary" and r.candidates[0].url_anchor is None
