"""The `_meta` block: every field of SPEC §4 present, activations with reasons, "no model"."""

from test_retrieval_fixtures import DICTIONARY, make_tables, plan_for, q_garantie, q_permis

from guide_rag.generation.pipeline import PIPELINE_VERSION, answer_question

META_FIELDS = {"question_id", "index_version", "pipeline_version", "methods_used", "methods_skipped", "activations", "chunk_strategy",
               "model_used", "prompt_version", "fragments_applied", "iterations", "validator_report", "timings_ms"}


def test_meta_is_complete():
    q = q_garantie()
    m = answer_question(q, plan_for(q), make_tables(), DICTIONARY).meta
    assert META_FIELDS <= set(m.model_dump())
    assert m.question_id == "q1" and m.index_version == "idx-test-1" and m.pipeline_version == PIPELINE_VERSION
    assert m.model_used == "no model" and m.prompt_version is None and m.fragments_applied == []
    assert m.iterations == 1 and m.validator_report == {"iteration_1": []}
    assert {"retrieval", "generation", "validation", "total"} <= set(m.timings_ms)
    assert "anchor = hit lines" in m.chunk_strategy and "answer_context=line" in m.chunk_strategy


def test_activations_carry_on_and_reason():
    q = q_garantie()
    m = answer_question(q, plan_for(q), make_tables(), DICTIONARY).meta
    acts = {k: (v.on, v.reason) for k, v in m.activations.items()}
    assert acts["use_keywords"] == (True, "always on")
    assert acts["use_embeddings"] == (False, "no vocabulary mismatch expected beyond the dictionary; keywords prove absence")
    assert acts["use_row_level"] == (True, "answer_type asks for an amount or a date")
    assert acts["current_page_boost"] == (False, "no pages_hint")
    assert set(acts) >= {"use_toc", "use_llm_arbiter", "use_llm_generation", "sweep_for_absence"}


def test_meta_methods_match_the_retrieval():
    q = q_permis()
    r = answer_question(q, plan_for(q), make_tables(), DICTIONARY)
    assert r.meta.methods_used == r.trace.retrieval.methods_used
    assert r.meta.methods_skipped == r.trace.retrieval.methods_skipped
    assert "absence" in r.meta.timings_ms
