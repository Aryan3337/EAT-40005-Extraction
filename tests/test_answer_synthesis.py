"""Tests for rag.py's AnswerSynthesizer.answer() -- its timeout and default model.

WHY THIS EXISTS: benchmarked on this machine's CPU Ollama, deepseek-r1:7b
(the model in use at the time) took 40.8s and mistral:7b took 40.3s to
synthesize a real answer. The timeout passed to requests.post was 30s --
below both -- so every real call timed out and silently fell back to the
templated response. Good prose was being generated and thrown away on every
single query.

Raising the timeout to 90s was not the full fix: measured 2026-10-05, 2 of 3
real deepseek-r1:7b calls still exceeded it and fell back to the template,
including one live chat request the user watched happen. deepseek-r1 is a
"thinking" model whose internal reasoning length varies the actual
wall-clock time unpredictably; mistral:7b has no such overhead and was
consistent across every benchmark run, so it is now the default model.
"""

import requests

from rag import (
    ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS,
    ANSWER_SYNTHESIS_TIMEOUT_SECONDS,
    AnswerSynthesizer,
    load_demo_answer_cache,
)


def _triple(**overrides):
    triple = {
        "subject": "GaroPeople",
        "predicate": "BILINGUAL",
        "object": "Bengali",
        "sentence_ref": "The majority of Garo people are bilingual.",
    }
    triple.update(overrides)
    return triple


def test_the_timeout_clears_the_slowest_benchmarked_default_model():
    # deepseek-r1:7b measured at 40.8s; mistral:7b (the default model) at
    # 40.3s. The timeout must clear both with real headroom, not just barely.
    assert ANSWER_SYNTHESIS_TIMEOUT_SECONDS >= 60


def test_the_default_model_has_no_reasoning_token_overhead():
    # deepseek-r1:7b is a "thinking" model whose internal reasoning length
    # varies unpredictably -- 2 of 3 real calls exceeded even the 90s
    # timeout on 2026-10-05, including one live chat request. mistral:7b has
    # no such overhead and was the consistent one across every benchmark.
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate")
    assert synthesizer.model == "mistral:7b"


def test_the_configured_timeout_is_the_one_actually_sent(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["timeout"] = timeout
        raise requests.Timeout("simulated")

    monkeypatch.setattr("rag.requests.post", fake_post)
    # answer_cache={} isolates this from data/demo_answer_cache.json -- this
    # question is one of the real cached prompts, and this test is about the
    # live-call path, not the cache short-circuit covered below.
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert captured["timeout"] == (ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS, ANSWER_SYNTHESIS_TIMEOUT_SECONDS)


def test_the_connect_timeout_is_short_so_a_dark_tunnel_fails_fast():
    # The hosted demo's OLLAMA_URL points at a Tailscale Funnel tunnel to a
    # laptop that is only turned on during the live demo. The rest of the
    # time nothing is listening there, so this has to be short -- not the
    # full 90s -- or every uncached question makes a real visitor wait a
    # minute and a half before seeing the templated fallback.
    assert ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS <= 15
    assert ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS < ANSWER_SYNTHESIS_TIMEOUT_SECONDS


def test_a_timeout_still_falls_back_to_the_templated_answer(monkeypatch):
    # The fallback path itself is a pre-existing feature; this just locks in
    # that raising the timeout did not remove the safety net for the case
    # where Ollama is genuinely slower than even the new ceiling.
    def fake_post(url, json, timeout):
        raise requests.Timeout("simulated")

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    answer = synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert "bilingual" in answer.lower()


def test_a_response_within_the_timeout_is_used_as_is(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"response": "The Garo are bilingual in Bengali."}

    def fake_post(url, json, timeout):
        return FakeResponse()

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate", answer_cache={})
    answer = synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert answer == "The Garo are bilingual in Bengali."


# -- the demo answer cache -----------------------------------------------------


def test_a_cached_question_short_circuits_the_live_call(monkeypatch):
    def fake_post(url, json, timeout):
        raise AssertionError("Ollama should not be called for a cached question")

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(
        ollama_url="http://localhost:11434/api/generate",
        answer_cache={"where do the garo live?": "They live in the Garo Hills."},
    )
    answer = synthesizer.answer("Where do the Garo live?", [_triple()])

    assert answer == "They live in the Garo Hills."


def test_cache_lookup_ignores_case_and_surrounding_whitespace():
    synthesizer = AnswerSynthesizer(
        ollama_url="http://localhost:11434/api/generate",
        answer_cache={"where do the garo live?": "They live in the Garo Hills."},
    )
    answer = synthesizer.answer("  WHERE DO THE GARO LIVE?  ", [_triple()])

    assert answer == "They live in the Garo Hills."


def test_an_uncached_question_is_not_affected_by_a_nonempty_cache(monkeypatch):
    def fake_post(url, json, timeout):
        raise requests.Timeout("simulated")

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(
        ollama_url="http://localhost:11434/api/generate",
        answer_cache={"where do the garo live?": "They live in the Garo Hills."},
    )
    answer = synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert "bilingual" in answer.lower()


def test_loading_a_missing_cache_file_returns_empty(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert load_demo_answer_cache(missing) == {}


def test_loading_the_cache_file_normalizes_its_keys(tmp_path):
    cache_file = tmp_path / "cache.json"
    cache_file.write_text(
        '{"  Where Do The Garo Live?  ": "They live in the Garo Hills."}',
        encoding="utf-8",
    )
    cache = load_demo_answer_cache(cache_file)

    assert cache == {"where do the garo live?": "They live in the Garo Hills."}
