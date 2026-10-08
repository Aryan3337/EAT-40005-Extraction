"""Tests for answering in the language picked in the app (English, Hindi, Bangla).

The graph and its keyword retrieval are English. A Bangla question must
still retrieve evidence (via LLM translation, or the glossary when the LLM
is down), and the answer must come back in Bangla -- without changing
anything for English requests, which send no language at all.
"""

import io
import json

import requests

import pytest

import rag
from rag import (
    AnswerSynthesizer,
    create_query_handler,
    glossary_keywords,
    normalize_language,
)


_real_mymemory_translate = rag.mymemory_translate


@pytest.fixture(autouse=True)
def _llm_translation_by_default(monkeypatch):
    # Most tests below cover the local-LLM path; the Google tests switch it.
    monkeypatch.setenv("TRANSLATION_PROVIDER", "llm")
    # Never reach the real MyMemory service from a test; the MyMemory tests
    # call _real_mymemory_translate with a fake translator instead.
    monkeypatch.setattr(rag, "mymemory_translate", lambda *a: "")
    monkeypatch.setattr(rag, "_mymemory_blocked_until", 0.0)
    monkeypatch.setattr(rag, "_google_blocked_until", 0.0)


def _triple():
    return {
        "subject": "GaroPeople",
        "predicate": "BILINGUAL",
        "object": "Bengali",
        "sentence_ref": "The majority of Garo people are bilingual.",
    }


def _synth(cache=None):
    return AnswerSynthesizer(ollama_url="http://localhost:11434/api/generate",
                             answer_cache=cache or {})


class _Response:
    def __init__(self, text):
        self.status_code = 200
        self._text = text

    def json(self):
        return {"response": self._text}


def test_unknown_or_missing_language_falls_back_to_english():
    assert normalize_language(None) == "en"
    assert normalize_language("") == "en"
    assert normalize_language("fr") == "en"
    assert normalize_language("bn") == "bn"
    assert normalize_language("bn_BD") == "bn"
    assert normalize_language("hi-IN") == "hi"


def test_english_prompt_is_unchanged_by_the_language_feature():
    prompt = _synth()._build_prompt("Where do the Garo live?", [_triple()])
    assert "Write the whole answer in" not in prompt


def test_bangla_prompt_asks_for_a_bangla_answer():
    prompt = _synth()._build_prompt("গারোরা কোথায় থাকে?", [_triple()], "bn")
    assert "Write the whole answer in Bengali (Bangla)" in prompt
    assert "গারোরা কোথায় থাকে?" in prompt


def test_no_evidence_message_is_in_the_chosen_language():
    assert "তথ্য" in _synth().answer("প্রশ্ন", [], "bn")
    assert _synth().answer("question", []).startswith("I could not find")


def test_english_cache_is_not_served_to_bangla_requests(monkeypatch):
    calls = []

    def fake_post(url, json, timeout, headers=None):
        calls.append(json["prompt"])
        return _Response("গারোরা দ্বিভাষিক।")

    monkeypatch.setattr(rag.requests, "post", fake_post)
    synth = _synth(cache={"what language do the garo speak?": "English cached answer"})

    assert synth.answer("What language do the Garo speak?", [_triple()]) == "English cached answer"
    assert synth.answer("What language do the Garo speak?", [_triple()], "bn") == "গারোরা দ্বিভাষিক।"
    assert len(calls) == 1


def test_llm_down_gives_english_fallback_with_a_bangla_note(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("tunnel off")

    monkeypatch.setattr(rag.requests, "post", fake_post)
    answer = _synth().answer("গারোরা কোন ভাষায় কথা বলে?", [_triple()], "bn")
    assert answer.startswith("(এই মুহূর্তে বাংলায়")
    assert "Based on the available knowledge" in answer


def test_english_questions_skip_translation(monkeypatch):
    def fail_post(*args, **kwargs):
        raise AssertionError("English must not call the LLM for translation")

    monkeypatch.setattr(rag.requests, "post", fail_post)
    question = "What language do the A·chik speak?"
    assert _synth().question_for_retrieval(question, "bn") == question


def test_bangla_question_is_translated_for_retrieval(monkeypatch):
    monkeypatch.setattr(rag.requests, "post",
                        lambda *a, **k: _Response("What language do the Garo speak?"))
    search = _synth().question_for_retrieval("গারোরা কোন ভাষায় কথা বলে?", "bn")
    assert "What language do the Garo speak?" in search
    assert "garo" in rag.question_keywords(search)


def test_glossary_keeps_retrieval_working_when_the_llm_is_down(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("tunnel off")

    monkeypatch.setattr(rag.requests, "post", fake_post)
    search = _synth().question_for_retrieval("গারোদের ভাষা কী?", "bn")
    keywords = rag.question_keywords(search)
    assert "garo" in keywords and "language" in keywords


def test_glossary_matches_inflected_bangla_words():
    assert "garo" in glossary_keywords("গারোদের সমস্যা")
    assert "challenge" in glossary_keywords("গারোদের সমস্যা")


class _FakeSkeleton:
    def __init__(self):
        self.queries = []

    def query(self, question, top_k=10):
        self.queries.append(question)
        return [_triple()]

    def format_output(self, triples):
        return ""

    def close(self):
        pass


class _FakeSynth:
    def __init__(self):
        self.languages = []

    def english_question(self, question, language="en"):
        return "translated" if language != "en" else question

    def question_for_retrieval(self, question, language="en", translated=None):
        return translated

    def answer(self, question, triples, language="en", english_question=None):
        self.languages.append(language)
        return f"answer in {language}"


def _post(handler_cls, body):
    raw = json.dumps(body).encode("utf-8")
    handler = handler_cls.__new__(handler_cls)
    handler.path = "/query"
    handler.headers = {"Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    sent = {}
    handler._send_json = lambda status, payload: sent.update(status=status, payload=payload)
    handler.do_POST()
    return sent


def test_query_endpoint_passes_the_language_through():
    skeleton, synth = _FakeSkeleton(), _FakeSynth()
    handler_cls = create_query_handler(skeleton, synth)

    sent = _post(handler_cls, {"query": "গারোরা কোথায় থাকে?", "language": "bn"})
    assert sent["status"] == 200
    assert sent["payload"]["answer"] == "answer in bn"
    assert sent["payload"]["language"] == "bn"
    assert skeleton.queries[-1] == "translated"


def test_query_endpoint_defaults_to_english_without_a_language():
    skeleton, synth = _FakeSkeleton(), _FakeSynth()
    sent = _post(create_query_handler(skeleton, synth), {"query": "Where do the Garo live?"})
    assert sent["payload"]["answer"] == "answer in en"
    assert skeleton.queries[-1] == "Where do the Garo live?"


# ---------------------------------------------------------------- Google path

def test_auto_is_the_default_provider(monkeypatch):
    monkeypatch.delenv("TRANSLATION_PROVIDER", raising=False)
    assert rag.translation_provider() == "auto"
    monkeypatch.setenv("TRANSLATION_PROVIDER", "nonsense")
    assert rag.translation_provider() == "auto"
    monkeypatch.setenv("TRANSLATION_PROVIDER", "google")
    assert rag.translation_provider() == "online"


def test_google_answers_bangla_without_any_llm(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "google")

    def no_llm(*args, **kwargs):
        raise requests.ConnectionError("Ollama is not installed")

    calls = []

    def fake_google(text, source, target):
        calls.append((source, target))
        return "গারোরা দ্বিভাষিক।" if target == "bn" else "What language do the Garo speak?"

    monkeypatch.setattr(rag.requests, "post", no_llm)
    monkeypatch.setattr(rag, "google_translate", fake_google)
    synth = _synth()

    english_q = synth.english_question("গারোরা কোন ভাষায় কথা বলে?", "bn")
    assert english_q == "What language do the Garo speak?"
    answer = synth.answer("গারোরা কোন ভাষায় কথা বলে?", [_triple()], "bn", english_q)
    assert answer == "গারোরা দ্বিভাষিক।"
    assert calls == [("bn", "en"), ("en", "bn")]


def test_google_path_reuses_the_english_demo_cache(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "google")
    seen = []
    monkeypatch.setattr(rag, "google_translate",
                        lambda text, s, t: seen.append(text) or "বাংলা উত্তর")
    synth = _synth(cache={"where do the garo live?": "Cached English answer"})
    assert synth.answer("গারোরা কোথায় বাস করে?", [_triple()], "bn",
                        "Where do the Garo live?") == "বাংলা উত্তর"
    assert seen == ["Cached English answer"]


def test_google_down_shows_english_with_a_note(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "google")
    monkeypatch.setattr(rag, "google_translate", lambda *a: "")
    synth = _synth(cache={"where do the garo live?": "Cached English answer"})
    answer = synth.answer("x", [_triple()], "bn", "Where do the Garo live?")
    assert answer.startswith("(এই মুহূর্তে বাংলায়")
    assert answer.endswith("Cached English answer")


def test_google_english_requests_are_never_translated(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "google")
    monkeypatch.setattr(rag, "google_translate",
                        lambda *a: pytest.fail("English must not be translated"))
    synth = _synth(cache={"where do the garo live?": "Cached"})
    assert synth.english_question("Where do the Garo live?", "en") == "Where do the Garo live?"
    assert synth.answer("Where do the Garo live?", [_triple()]) == "Cached"


def test_google_translate_returns_empty_on_errors(monkeypatch):
    import deep_translator

    class Broken:
        def __init__(self, **kwargs):
            pass

        def translate(self, text):
            raise RuntimeError("no network")

    monkeypatch.setattr(deep_translator, "GoogleTranslator", Broken)
    assert rag.google_translate("hello", "en", "bn") == ""
    assert rag.google_translate("   ", "en", "bn") == ""


def test_google_translate_splits_long_text(monkeypatch):
    import deep_translator
    sizes = []

    class Recorder:
        def __init__(self, **kwargs):
            pass

        def translate(self, text):
            sizes.append(len(text))
            return "x"

    monkeypatch.setattr(deep_translator, "GoogleTranslator", Recorder)
    long_text = "\n\n".join(["word " * 600] * 3)  # ~9000 chars
    assert rag.google_translate(long_text, "en", "bn") == "x\n\nx\n\nx"
    assert max(sizes) <= 4500


# ------------------------------------------------------------------ auto path

def test_auto_falls_back_to_the_local_model_when_google_refuses(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "auto")
    monkeypatch.setattr(rag, "google_translate", lambda *a: "")
    prompts = []

    def fake_post(url, json, timeout, headers=None):
        prompts.append(json["prompt"])
        if json["prompt"].startswith("Translate this question"):
            return _Response("Where do the Garo live?")
        if json["prompt"].startswith("Translate the following text"):
            return _Response("গারোরা ময়মনসিংহে বাস করে।")
        return _Response("The Garo live in Mymensingh.")

    monkeypatch.setattr(rag.requests, "post", fake_post)
    synth = _synth()
    english_q = synth.english_question("গারোরা কোথায় বাস করে?", "bn")
    assert english_q == "Where do the Garo live?"
    assert synth.answer("গারোরা কোথায় বাস করে?", [_triple()], "bn", english_q) \
        == "গারোরা ময়মনসিংহে বাস করে।"
    assert len(prompts) == 3


def test_auto_uses_google_and_skips_the_model_when_google_works(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "auto")
    monkeypatch.setattr(rag, "google_translate", lambda text, s, t: "বাংলা উত্তর")
    synth = _synth(cache={"where do the garo live?": "Cached"})
    monkeypatch.setattr(rag.requests, "post",
                        lambda *a, **k: pytest.fail("no LLM call expected"))
    assert synth.answer("x", [_triple()], "bn", "Where do the Garo live?") == "বাংলা উত্তর"


def test_google_429_starts_a_cooldown(monkeypatch):
    import deep_translator
    calls = []

    class TooManyRequests(Exception):
        pass

    class Limited:
        def __init__(self, **kwargs):
            pass

        def translate(self, text):
            calls.append(text)
            raise TooManyRequests()

    monkeypatch.setattr(deep_translator, "GoogleTranslator", Limited)
    monkeypatch.setattr(rag, "_google_blocked_until", 0.0)
    assert rag.google_translate("one", "en", "bn") == ""
    assert rag.google_translate("two", "en", "bn") == ""
    assert calls == ["one"]


def test_translated_answers_get_more_tokens_and_time(monkeypatch):
    seen = {}

    def fake_post(url, json, timeout, headers=None):
        seen["tokens"] = json["options"]["num_predict"]
        seen["timeout"] = timeout
        return _Response("উত্তর")

    monkeypatch.setattr(rag.requests, "post", fake_post)
    _synth().answer("প্রশ্ন", [_triple()], "bn")
    assert seen["tokens"] == rag.TRANSLATED_ANSWER_MAX_TOKENS
    assert seen["timeout"][1] == rag.TRANSLATION_TIMEOUT_SECONDS


# ------------------------------------------------------------- MyMemory path

class _FakeMyMemory:
    calls = []
    reply = "অনুবাদ"

    def __init__(self, source, target, email=None):
        self.source, self.target = source, target

    def translate(self, text):
        _FakeMyMemory.calls.append((self.source, self.target, len(text)))
        return _FakeMyMemory.reply


def test_mymemory_backs_up_google_without_any_llm(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "auto")
    monkeypatch.setattr(rag, "google_translate", lambda *a: "")
    monkeypatch.setattr(rag, "mymemory_translate",
                        lambda text, s, t: "Where do the Garo live?" if t == "en" else "গারোরা ময়মনসিংহে বাস করে।")
    monkeypatch.setattr(rag.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("no Ollama")))
    synth = _synth(cache={"where do the garo live?": "The Garo live in Mymensingh."})
    english_q = synth.english_question("গারোরা কোথায় বাস করে?", "bn")
    assert english_q == "Where do the Garo live?"
    assert synth.answer("গারোরা কোথায় বাস করে?", [_triple()], "bn", english_q) \
        == "গারোরা ময়মনসিংহে বাস করে।"


def test_online_mode_never_calls_the_local_model(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "online")
    monkeypatch.setattr(rag, "google_translate", lambda *a: "")
    monkeypatch.setattr(rag.requests, "post",
                        lambda *a, **k: pytest.fail("online mode must not call Ollama"))
    synth = _synth(cache={"where do the garo live?": "Cached"})
    assert synth.english_question("গারোরা কোথায় বাস করে?", "bn") == ""
    answer = synth.answer("x", [_triple()], "bn", "Where do the Garo live?")
    assert answer.endswith("Cached")


def test_mymemory_uses_its_language_codes_and_splits_long_text(monkeypatch):
    import deep_translator
    _FakeMyMemory.calls = []
    _FakeMyMemory.reply = "অনুবাদ"
    monkeypatch.setattr(deep_translator, "MyMemoryTranslator", _FakeMyMemory)
    text = "This is one sentence about the Garo people. " * 30  # ~1300 chars
    result = _real_mymemory_translate(text, "en", "bn")
    assert result
    assert {(s, t) for s, t, _ in _FakeMyMemory.calls} == {("en-GB", "bn-IN")}
    assert max(n for _, _, n in _FakeMyMemory.calls) <= 480
    assert len(_FakeMyMemory.calls) >= 3


def test_mymemory_cannot_auto_detect(monkeypatch):
    import deep_translator
    _FakeMyMemory.calls = []
    monkeypatch.setattr(deep_translator, "MyMemoryTranslator", _FakeMyMemory)
    assert _real_mymemory_translate("hello", "auto", "bn") == ""
    assert _FakeMyMemory.calls == []


def test_mymemory_quota_warning_counts_as_failure(monkeypatch):
    import deep_translator
    _FakeMyMemory.calls = []
    _FakeMyMemory.reply = "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY."
    monkeypatch.setattr(deep_translator, "MyMemoryTranslator", _FakeMyMemory)
    assert _real_mymemory_translate("hello", "en", "bn") == ""
    assert _real_mymemory_translate("again", "en", "bn") == ""  # cooling down
    assert len(_FakeMyMemory.calls) == 1


def test_split_keeps_every_word():
    text = "First sentence here. Second one! Third?\n\nNew paragraph."
    pieces = rag._split_for_limit(text, 25)
    assert all(len(p) <= 25 for p in pieces)
    assert " ".join(pieces).split() == text.split()


# ---------------------------------------------------------------------- Hindi

def test_hindi_answers_through_the_online_services(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "auto")
    calls = []

    def fake_google(text, source, target):
        calls.append((source, target))
        return "Where do the Garo live?" if target == "en" else "गारो लोग मैमनसिंह में रहते हैं।"

    monkeypatch.setattr(rag, "google_translate", fake_google)
    synth = _synth(cache={"where do the garo live?": "The Garo live in Mymensingh."})
    english_q = synth.english_question("गारो लोग कहाँ रहते हैं?", "hi")
    assert english_q == "Where do the Garo live?"
    assert synth.answer("गारो लोग कहाँ रहते हैं?", [_triple()], "hi", english_q) \
        == "गारो लोग मैमनसिंह में रहते हैं।"
    assert calls == [("hi", "en"), ("en", "hi")]


def test_hindi_glossary_matches_the_suggested_questions():
    for question, expected in [
        ("गारो लोग कहाँ रहते हैं?", {"garo", "live"}),
        ("गारो लोग कौन सी भाषा बोलते हैं?", {"garo", "language"}),
        ("गारो समुदाय किन चुनौतियों का सामना करता है?", {"garo", "challenge", "community"}),
    ]:
        assert expected <= set(glossary_keywords(question).split()), question


def test_hindi_fallback_note_is_in_hindi(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "online")
    monkeypatch.setattr(rag, "google_translate", lambda *a: "")
    synth = _synth(cache={"where do the garo live?": "Cached"})
    answer = synth.answer("x", [_triple()], "hi", "Where do the Garo live?")
    assert answer.startswith("(अभी हिंदी में")
    assert "किसी" in rag._NO_EVIDENCE_MESSAGES["hi"]


def test_mymemory_knows_hindi():
    assert rag._MYMEMORY_CODES["hi"] == "hi-IN"
