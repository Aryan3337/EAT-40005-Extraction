"""Tests for rag.py's AnswerSynthesizer.answer() -- specifically its timeout.

WHY THIS EXISTS: benchmarked on this machine's CPU Ollama, the default model
(deepseek-r1:7b) took 40.8s and mistral:7b took 40.3s to synthesize a real
answer. The timeout passed to requests.post was 30s -- below both -- so
every real call timed out and silently fell back to the templated response.
Good prose was being generated and thrown away on every single query.
"""

import requests

from rag import ANSWER_SYNTHESIS_TIMEOUT_SECONDS, AnswerSynthesizer


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
    # deepseek-r1:7b (the default model) measured at 40.8s; mistral:7b at
    # 40.3s. The timeout must clear both with real headroom, not just barely.
    assert ANSWER_SYNTHESIS_TIMEOUT_SECONDS >= 60


def test_the_configured_timeout_is_the_one_actually_sent(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured["timeout"] = timeout
        raise requests.Timeout("simulated")

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate")
    synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert captured["timeout"] == ANSWER_SYNTHESIS_TIMEOUT_SECONDS


def test_a_timeout_still_falls_back_to_the_templated_answer(monkeypatch):
    # The fallback path itself is a pre-existing feature; this just locks in
    # that raising the timeout did not remove the safety net for the case
    # where Ollama is genuinely slower than even the new ceiling.
    def fake_post(url, json, timeout):
        raise requests.Timeout("simulated")

    monkeypatch.setattr("rag.requests.post", fake_post)
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate")
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
    synthesizer = AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate")
    answer = synthesizer.answer("What language do the Garo speak?", [_triple()])

    assert answer == "The Garo are bilingual in Bengali."
