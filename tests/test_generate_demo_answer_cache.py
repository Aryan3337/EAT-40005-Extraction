"""Tests for generate_demo_answer_cache.py's refusal to cache a non-answer.

WHY THIS EXISTS: the script already refused to cache _fallback_answer's
templated output (detected via _FALLBACK_PREFIX), but rag.py's relevance
gate (added 2026-10-08) can make AnswerSynthesizer.answer() return
NO_GROUNDED_ANSWER_MESSAGE on the exact same success path -- a 200 response
with real text, just one the model's own RELEVANT: no marker rejected. The
script's docstring says to re-run it whenever the prompts or the production
graph change, so if a scripted demo question gates "no" during such a
re-run, the refusal would get written into data/demo_answer_cache.json and
served instantly forever. Cached answers deliberately bypass the gate (see
rag.py's answer()), so SYNTHESIS_RELEVANCE_GATE=0 would NOT undo this --
there would be no working rollback for a refusal baked into the cache.
"""

import json

import generate_demo_answer_cache
from rag import NO_GROUNDED_ANSWER_MESSAGE


def _triple():
    return {
        "subject": "GaroPeople",
        "predicate": "BILINGUAL",
        "object": "Bengali",
        "sentence_ref": "The majority of Garo people are bilingual.",
    }


class _FakeSkeleton:
    """Stands in for Neo4jRAGSkeleton: never touches a real database."""

    def __init__(self):
        pass

    def query(self, question):
        return [_triple()]

    def close(self):
        pass


def _patch_common(monkeypatch, tmp_path, fake_synthesizer_cls):
    cache_path = tmp_path / "demo_answer_cache.json"
    monkeypatch.setattr("generate_demo_answer_cache.DEMO_ANSWER_CACHE_PATH", cache_path)
    monkeypatch.setattr("generate_demo_answer_cache.Neo4jRAGSkeleton", _FakeSkeleton)
    monkeypatch.setattr("generate_demo_answer_cache.AnswerSynthesizer", fake_synthesizer_cls)
    return cache_path


def test_a_gated_refusal_is_not_written_to_the_cache(monkeypatch, tmp_path):
    class _FakeSynthesizer:
        def __init__(self, answer_cache=None):
            pass

        def answer(self, question, triples):
            return NO_GROUNDED_ANSWER_MESSAGE

    cache_path = _patch_common(monkeypatch, tmp_path, _FakeSynthesizer)

    exit_code = generate_demo_answer_cache.main()

    # Every scripted question refused -- nothing to write at all, and the
    # non-zero exit code is the same signal a timed-out fallback gives today.
    assert exit_code == 1
    assert not cache_path.exists()


def test_only_the_gated_question_is_excluded_not_the_whole_run(monkeypatch, tmp_path):
    refused_question = generate_demo_answer_cache.SCRIPTED_QUESTIONS[0]

    class _FakeSynthesizer:
        def __init__(self, answer_cache=None):
            pass

        def answer(self, question, triples):
            if question == refused_question:
                return NO_GROUNDED_ANSWER_MESSAGE
            return "A real synthesized answer."

    cache_path = _patch_common(monkeypatch, tmp_path, _FakeSynthesizer)

    exit_code = generate_demo_answer_cache.main()

    # Problems were recorded (the refusal), so this must still surface
    # non-zero even though the other questions cached fine.
    assert exit_code == 1
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert refused_question not in cache
    assert len(cache) == len(generate_demo_answer_cache.SCRIPTED_QUESTIONS) - 1
