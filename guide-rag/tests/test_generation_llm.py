"""The optional model path, never called for real: the transport is mocked with httpx.MockTransport."""

import json

import httpx
import pytest
from test_retrieval_fixtures import DICTIONARY, make_tables, plan_for, q_bail, q_garantie

from guide_rag.generation.llm import (PROMPT_VERSION, LLMClient, LLMConfig, NotConfigured, build_prompt, generate_with_llm,
                                      response_schema)
from guide_rag.generation.pipeline import answer_question
from guide_rag.generation.validator import validate
from guide_rag.retrieval.result import retrieve

LINE_4 = "Le bail est le contrat de location signé entre le locataire et le propriétaire."


def client_returning(payload: dict, seen: dict | None = None) -> LLMClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    return LLMClient(LLMConfig(base_url="https://llm.test/v1", api_key="test-key", model="test-model"), transport=httpx.MockTransport(handler))


def test_not_configured_without_a_key(monkeypatch):
    monkeypatch.delenv("GUIDE_RAG_LLM_KEY", raising=False)
    with pytest.raises(NotConfigured):
        LLMConfig.from_env()
    monkeypatch.setenv("GUIDE_RAG_LLM_KEY", "k")
    monkeypatch.setenv("GUIDE_RAG_LLM_BASE_URL", "https://llm.test/v1/")
    monkeypatch.setenv("GUIDE_RAG_LLM_MODEL", "m")
    assert LLMConfig.from_env() == LLMConfig("https://llm.test/v1", "k", "m")


def test_request_is_temperature_zero_with_json_schema_and_quotes_come_from_line_df():
    t = make_tables()
    q = q_bail()
    r = retrieve(q, plan_for(q), t, DICTIONARY)
    seen: dict = {}
    client = client_returning({"answer_found": True, "complete_answer_found": True,
                               "items": [{"text": "the model's own words", "spans": [{"doc_id": "logement", "line_start": 4, "line_end": 4}]}],
                               "discovered_keywords": ["locataire"], "caveats": []}, seen)
    answer, info = generate_with_llm(q, r, t, client)
    assert seen["url"] == "https://llm.test/v1/chat/completions" and seen["auth"] == "Bearer test-key"
    assert seen["body"]["temperature"] == 0 and seen["body"]["model"] == "test-model"
    assert seen["body"]["response_format"]["type"] == "json_schema" and seen["body"]["response_format"]["json_schema"]["strict"] is True
    # The model gave line numbers; the quote and the displayed text are the line itself (rule 3).
    assert answer.items[0].spans[0].quote == LINE_4 and answer.items[0].text == LINE_4
    assert answer.llm_discovered_keywords == ["locataire"] and answer.extraction_method == "verbatim"
    assert info.model_used == "test-model" and info.prompt_version == PROMPT_VERSION
    assert info.fragments_applied == ["base", "shape:text", "constraints"]
    assert validate(answer, t.line_df, q) == []


def test_prompt_shows_numbered_lines_and_one_shape_fragment():
    t = make_tables()
    q = q_garantie()
    system, user, fragments = build_prompt(q, retrieve(q, plan_for(q), t, DICTIONARY), t, "amount")
    assert fragments == ["base", "shape:amount", "constraints"]
    assert "Shape amount" in system and "Shape text" not in system and "never copy a passage" in system
    assert "[logement#l9-l10] Logement › Garantie locative (primary)" in user and "logement L10: Elle correspond" in user


def test_span_outside_the_lines_has_no_quote_and_fails_validation():
    t = make_tables()
    q = q_bail()
    r = retrieve(q, plan_for(q), t, DICTIONARY)
    client = client_returning({"answer_found": True, "complete_answer_found": False,
                               "items": [{"text": "x", "spans": [{"doc_id": "logement", "line_start": 99, "line_end": 99}]}],
                               "discovered_keywords": [], "caveats": []})
    answer, _ = generate_with_llm(q, r, t, client)
    assert answer.items[0].spans[0].quote is None
    assert {p.code for p in validate(answer, t.line_df, q)} == {"span_outside_context"}


def test_pipeline_with_the_model_records_it_in_meta_and_rejects_on_failure():
    t = make_tables()
    q = q_garantie()
    client = client_returning({"answer_found": True, "complete_answer_found": True,
                               "items": [{"value": 1500, "currency": "EUR", "unit": None, "spans": [{"doc_id": "logement", "line_start": 10, "line_end": 10}]}],
                               "discovered_keywords": [], "caveats": []})
    r = answer_question(q, plan_for(q, llm=True), t, DICTIONARY, llm_client=client)
    assert r.meta.model_used == "test-model" and r.meta.prompt_version == PROMPT_VERSION and r.meta.fragments_applied == ["base", "shape:amount", "constraints"]
    assert r.answer.items[0].amount.value == 1500.0 and r.answer.extraction_method == "computed" and r.meta.iterations == 1

    bad = client_returning({"answer_found": True, "complete_answer_found": True,
                            "items": [{"value": 1500, "currency": "EUR", "unit": None, "spans": [{"doc_id": "logement", "line_start": 10, "line_end": 9}]}],
                            "discovered_keywords": ["caution"], "caveats": []})
    r2 = answer_question(q, plan_for(q, llm=True), t, DICTIONARY, llm_client=bad)
    assert r2.meta.iterations == 2 and not r2.answer.answer_found and r2.answer.caveats[0].startswith("Rejected by the validator")


def test_response_schema_per_kind():
    for kind, keys in {"text": {"text"}, "list": {"text"}, "amount": {"value", "currency", "unit"}, "date": {"iso", "original"}, "boolean": {"boolean"}}.items():
        schema = response_schema(kind)
        assert set(schema["properties"]["items"]["items"]["properties"]) == keys | {"spans"}
        assert schema["required"] == ["answer_found", "complete_answer_found", "items", "discovered_keywords", "caveats"]
