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



class _LanguageTestAuthStore:
    def session(self, token):
        if token == "language-test-token":
            return {"email": "language-test@example.invalid", "role": "member"}
        return None


@pytest.fixture(autouse=True)
def _language_test_auth(monkeypatch):
    monkeypatch.setattr(rag, "AuthStore", _LanguageTestAuthStore)


def _post(handler_cls, body):
    raw = json.dumps(body).encode("utf-8")
    handler = handler_cls.__new__(handler_cls)
    handler.path = "/query"
    handler.headers = {
        "Content-Length": str(len(raw)),
        "Authorization": "Bearer language-test-token",
    }
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


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("hi", "गारो लोग मेघालय में रहते हैं।"),
        ("bn", "গারো মানুষ মেঘালয়ে বাস করে।"),
    ],
)
def test_query_endpoint_returns_the_answer_in_the_requested_language(
    monkeypatch, language, expected
):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "online")
    source = "The Garo people live in Meghalaya."
    translated = {
        "hi": "गारो लोग मेघालय में रहते हैं।",
        "bn": "গারো মানুষ মেঘালয়ে বাস করে।",
    }
    calls = []

    def fake_translate(text, source_language, target_language):
        calls.append((source_language, target_language))
        return translated.get(target_language, "")

    monkeypatch.setattr(rag, "online_translate", fake_translate)
    synthesizer = _synth(cache={"Where do the Garo people live?": source})
    response = _post(
        create_query_handler(_FakeSkeleton(), synthesizer),
        {"query": "Where do the Garo people live?", "language": language},
    )

    assert response["status"] == 200
    assert response["payload"]["language"] == language
    assert response["payload"]["answer"] == expected
    assert response["payload"]["translations"][language] == expected
    assert calls[0] == ("en", language)


def test_a_failed_translation_falls_back_to_english_rather_than_failing(
    monkeypatch,
):
    """A translation failure must not throw away a good English answer.

    Until 2026-10-28 this returned 503 and the user saw nothing at all --
    a teammate asking "what is Garo" in Hindi got "RAG request failed
    (HTTP 503)". That error handling came from 70f5107, when the provider
    was Google and a failure meant a real outage. Production now runs
    TRANSLATION_PROVIDER=llm, where an empty result is routine: a slow
    local model, a non-200 from Ollama, or an empty generation all return
    "" from _llm_translate, and every one of them discarded a correct
    answer the system had already computed.

    The non-selected languages have always degraded this way. Only the
    selected one raised.
    """
    monkeypatch.setenv("TRANSLATION_PROVIDER", "online")
    monkeypatch.setattr(rag, "online_translate", lambda *args: "")
    synthesizer = _synth(cache={"Where do the Garo people live?": "English answer"})

    response = _post(
        create_query_handler(_FakeSkeleton(), synthesizer),
        {"query": "Where do the Garo people live?", "language": "bn"},
    )

    assert response["status"] == 200
    assert response["payload"]["language"] == "bn"
    # The English answer survives, carried after the note.
    answer = response["payload"]["answer"]
    assert len(answer) > len(rag._ENGLISH_ONLY_NOTES["bn"])


def test_the_english_fallback_says_it_is_a_fallback(monkeypatch):
    """The point of the old 503 was not to pass English off as Bangla.
    That intent survives: the note is what carries it, in the reader's own
    language, so nobody mistakes an untranslated answer for a translated
    one."""
    monkeypatch.setenv("TRANSLATION_PROVIDER", "online")
    monkeypatch.setattr(rag, "online_translate", lambda *args: "")
    synthesizer = _synth(cache={"Where do the Garo people live?": "English answer"})

    response = _post(
        create_query_handler(_FakeSkeleton(), synthesizer),
        {"query": "Where do the Garo people live?", "language": "bn"},
    )

    answer = response["payload"]["answer"]
    assert answer.startswith(rag._ENGLISH_ONLY_NOTES["bn"])
    assert answer != "English answer"


def test_query_endpoint_defaults_to_english_without_a_language():
    skeleton, synth = _FakeSkeleton(), _FakeSynth()
    sent = _post(create_query_handler(skeleton, synth), {"query": "Where do the Garo live?"})
    assert sent["payload"]["answer"] == "answer in en"
    assert skeleton.queries[-1] == "Where do the Garo live?"


# ------------------------------------------------ Translation prompt rules
#
# KNOWN_LIMITATIONS 29, measured 2026-10-28 against the live instance: five
# of the five substantive Bangla answers were materially wrong, and eight of
# eight responses appended content nobody asked for -- a romanised
# transliteration, a full English back-translation, or an explanatory
# "Note:". The prompt the model was given said only "Return only the
# translation. Preserve names of people, places, and communities."
#
# These tests pin option 3 of that entry: the rules go on the ANSWER
# translation, which is what a reader sees. The QUESTION translation is
# deliberately left alone -- only its English meaning is used, to build a
# retrieval query, and loading it with answer-shaped rules would change
# retrieval while fixing nothing a user reads.


def _translation_prompt(monkeypatch, text, language, question=False):
    prompts = []

    def fake_post(url, json, timeout=None, headers=None):
        prompts.append(json["prompt"])
        return _Response("অনুবাদ")

    monkeypatch.setattr(rag.requests, "post", fake_post)
    synth = _synth()
    if question:
        synth.translate_question(text, language)
    else:
        synth.translate_answer(text, language)
    return prompts[-1]


def test_answer_translation_forbids_the_appendices_that_reached_users(
    monkeypatch,
):
    """All eight benchmark responses appended something unrequested."""
    prompt = _translation_prompt(
        monkeypatch, "The Garo live in Mymensingh.", "bn"
    ).lower()

    assert "transliteration" in prompt
    assert "back-translation" in prompt
    assert "note" in prompt


def test_answer_translation_forbids_adding_facts_the_text_does_not_have(
    monkeypatch,
):
    """Question 3 put Goalpara, Assam inside Bangladesh; an earlier run of
    the same question invented "northern Bangladesh". Question 4 supplied
    Tamarindus indica and Syzygium cumini -- correct botany the evidence
    never provided. Every one of those is a claim added at translation
    time, after the relevance gate and the refusal-over-bridging rule have
    already run."""
    prompt = _translation_prompt(
        monkeypatch, "The Garo live in Mymensingh.", "bn"
    ).lower()

    assert "do not add" in prompt
    assert "place" in prompt


def test_answer_translation_requires_quoted_text_to_keep_its_meaning(
    monkeypatch,
):
    """Question 2 inverted "almost abolished and practiced by very few"
    into "has begun" -- inside what the answer presents as a verbatim
    quote from Page 1."""
    prompt = _translation_prompt(
        monkeypatch,
        'The source says "almost abolished and practiced by very few".',
        "bn",
    ).lower()

    assert "quot" in prompt


def test_answer_translation_rules_reach_hindi_too(monkeypatch):
    """The appendices and the spliced-script faults were measured in both
    languages, so the rules cannot be Bangla-only."""
    prompt = _translation_prompt(
        monkeypatch, "The Garo live in Mymensingh.", "hi"
    ).lower()

    assert "transliteration" in prompt


def test_the_rules_carry_no_example_the_model_can_copy_out(monkeypatch):
    """Measured on the live model 2026-10-28: the first version of these
    rules ended with `Leave numbers, Latin-script names, and "(Source: Page
    N)" citations as they are`, and mistral:7b copied the literal
    placeholder `(Source: Page N)` into the Bangla and Hindi output -- a new
    appendix, invented by the instruction meant to stop appendices.

    A rule may describe what to preserve. It may not show a sample of it."""
    prompt = _translation_prompt(
        monkeypatch, "The Garo live in Mymensingh.", "bn"
    )

    assert "Page N" not in prompt
    assert "Note:" not in prompt


def test_question_translation_is_left_alone(monkeypatch):
    """The retrieval path is not what limitation 29 measured. Changing it
    here would alter which triples come back for every non-English
    question, to fix nothing a reader sees."""
    prompt = _translation_prompt(
        monkeypatch, "গারোরা কোথায় থাকে?", "bn", question=True
    ).lower()

    assert "transliteration" not in prompt
    assert "do not add" not in prompt


# ------------------------------------------- Stripping appended commentary
#
# Measured on the live model 2026-10-28, twice. Constraining the prompt
# (above) does NOT reliably stop the model appending things: of four
# answers translated with the rules in place, one still appended a full
# romanised transliteration and one appended `Source:
# https://www.britannica.com/topic/Garo-people` -- a citation to an
# external website, in a system whose entire design ties every claim to a
# retrieved triple. No English answer in the probe contained a URL, so the
# model invented it at translation time.
#
# So the appendix is removed deterministically as well. Every appendix
# observed in twelve probe calls sat in its own paragraph after a blank
# line and contained no character of the target script, which is what this
# keys on -- a translation's own text is in the script it was translated
# into.

_BANGLA_ANSWER = (
    "গাড়ো জাতি প্রথমত গাড়ো হিল্সে, মেঘালয়া, ভারত ও গোয়ালপারা, অসম, "
    "ভারত এবং মিমেসিংহ, বাংলাদেশে থাকে।"
)
_HINDI_ANSWER = (
    "गारो लोग प्राथमिकता से गारो हिल्स, मेघालय, भारत और बंगलादेश में रहते हैं।"
)


def test_a_trailing_transliteration_is_removed():
    text = _BANGLA_ANSWER + (
        "\n\n(Note: The transliteration of the Bengali text is: garo jati "
        "prathamat garo hills-e, meghalaya, bharat o goyalpara, assam.)"
    )
    assert rag.strip_translation_appendix(text, "bn") == _BANGLA_ANSWER


def test_a_trailing_english_back_translation_is_removed():
    text = _BANGLA_ANSWER + (
        "\n\n(Garo people, A·chik Mande or Mandi, primarily speak the Garo "
        "language. It is mentioned that the community maintains it.)"
    )
    assert rag.strip_translation_appendix(text, "bn") == _BANGLA_ANSWER


def test_a_trailing_translator_note_is_removed():
    text = _HINDI_ANSWER + (
        "\n\nTranslation Note: The names of the places and communities "
        "remain the same in both English and Hindi."
    )
    assert rag.strip_translation_appendix(text, "hi") == _HINDI_ANSWER


def test_a_fabricated_source_link_is_removed():
    text = _BANGLA_ANSWER + (
        "\n\nSource:\nhttps://www.britannica.com/topic/Garo-people"
    )
    assert rag.strip_translation_appendix(text, "bn") == _BANGLA_ANSWER


def test_latin_script_inside_the_translation_is_kept():
    """Plant names, place names and numbers are supposed to survive -- 31
    plants and 23 families carried through intact in the measurement, and
    the model leaves some proper nouns in Latin mid-sentence."""
    text = (
        "গাড়ো জাতি Mymensingh এ থাকে এবং Tamarindus indica ব্যবহার করে। "
        "৩১টি গাছ।"
    )
    assert rag.strip_translation_appendix(text, "bn") == text


def test_a_translation_with_nothing_appended_is_unchanged():
    assert rag.strip_translation_appendix(_BANGLA_ANSWER, "bn") == _BANGLA_ANSWER


def test_an_answer_that_is_all_english_is_left_alone():
    """When the model returns English instead of translating, the whole
    text would otherwise be stripped to nothing. That case belongs to the
    caller, which puts the English behind a note in the reader's script."""
    english = "The Garo people primarily reside in the Garo Hills."
    assert rag.strip_translation_appendix(english, "bn") == english


def test_a_short_citation_after_the_answer_survives():
    """Only commentary is removed. A page citation is provenance, and the
    rule that drops a paragraph is deliberately blind to meaning, so it is
    held to long blocks and links rather than anything Latin."""
    text = _BANGLA_ANSWER + "\n\n(Source: Page 1)"
    assert rag.strip_translation_appendix(text, "bn") == text


def test_translate_answer_removes_the_appendix_it_was_given(monkeypatch):
    """The wiring, not just the helper: what reaches a reader is stripped."""
    appended = _BANGLA_ANSWER + (
        "\n\n(Note: The transliteration is: garo jati prathamat garo hills-e, "
        "meghalaya, bharat o goyalpara, assam, bharat.)"
    )

    def fake_post(url, json, timeout=None, headers=None):
        return _Response(appended)

    monkeypatch.setattr(rag.requests, "post", fake_post)

    assert _synth().translate_answer("The Garo live in Mymensingh.", "bn") == (
        _BANGLA_ANSWER
    )


# ------------------------------- Ahmed's SCRUM-318 guards, on the llm path
#
# `translation_incomplete` and `restore_numbers` were written for SCRUM-318
# (`fe11814`) and are called from `online_translate`, `google_translate` and
# `mymemory_translate`. Production runs `TRANSLATION_PROVIDER=llm` for the
# privacy constraint, and `translate_answer` reads
# `elif provider != "llm"`, so none of them ever ran against the model that
# actually serves users. Both are pure string comparisons with no
# third-party call, so they port as they are.
#
# Measured over twenty real captured translations before porting: the
# detector flagged none of them and `restore_numbers` changed none of them.
# It is insurance against failures that sample did not contain, not a fix
# for anything observed -- which is why these tests pin the failures it DOES
# catch, and one that it must not.

_ENGLISH_ANSWER = (
    "The Garo people primarily reside in the Garo Hills, Meghalaya, India, "
    "and in neighbouring parts of Goalpara, Assam, as well as in "
    "Mymensingh, Bangladesh."
)


def _llm_returns(monkeypatch, text):
    def fake_post(url, json, timeout=None, headers=None):
        return _Response(text)

    monkeypatch.setattr(rag.requests, "post", fake_post)


def test_an_untranslated_english_answer_is_not_passed_off_as_bangla(
    monkeypatch,
):
    """The model sometimes returns its input. Until this guard reached the
    llm path, `translate_answer` saw a non-empty string, called it a
    translation, and the reader got English labelled as Bangla -- the exact
    thing `_ENGLISH_ONLY_NOTES` exists to prevent. Returning "" hands the
    decision back to the caller, which prefixes the note."""
    _llm_returns(monkeypatch, _ENGLISH_ANSWER)

    assert _synth().translate_answer(_ENGLISH_ANSWER, "bn") == ""


def test_a_translation_missing_half_its_content_is_rejected(monkeypatch):
    """TRANSLATED_ANSWER_MAX_TOKENS caps generation at 1500 tokens, and
    Bangla costs several tokens per character, so a long answer can be cut
    off mid-way. Half an answer is not an answer."""
    _llm_returns(monkeypatch, "গাড়ো জাতি।")

    assert _synth().translate_answer(_ENGLISH_ANSWER, "bn") == ""


def test_the_appendix_is_removed_before_the_completeness_check(monkeypatch):
    """Order matters, and the margin is thin. This pair is real: the Bangla
    is a captured translation of the answer below, the appendix is what the
    model actually appended, and together they score a Latin-word ratio of
    0.405 against the detector's 0.4 threshold -- so with the checks in the
    wrong order a sound translation is discarded for being "mostly
    English". The appendix is not part of the translation, so it has to be
    gone before anything measures it."""
    body = (
        "গাড়ো জাতি প্রথমত গাড়ো হিল্সে, মেঘালয়া, ভারত ও সম্মুখে থাকা "
        "গোয়ালপারা, অসম, ভারত এবং মিমেসিংহ, বাংলাদেশে থাকে।"
    )
    _llm_returns(monkeypatch, body + (
        "\n\n(Note: The transliteration of the Bengali text is: garo jati "
        "prathamat garo hills-e, meghalaya, bharat o sammukhe thaka "
        "goyalpara, assam, bharat e mimesingh, bangladesh-e thake.)"
    ))

    assert _synth().translate_answer(_ENGLISH_ANSWER, "bn") == body


def test_a_wrong_amount_is_replaced_by_the_english_one(monkeypatch):
    """Numbers are the one thing that survived the measurement in
    KNOWN_LIMITATIONS 29 intact, and this keeps it that way: the English
    answer's amount wins."""
    _llm_returns(monkeypatch, "গাড়ো জনসংখ্যা ৩০০, ০০০, ০০০ জন।")

    translated = _synth().translate_answer(
        "The Garo population is 3 million people.", "bn"
    )

    assert "৩০ লাখ" in translated
    assert "৩০০, ০০০, ০০০" not in translated


def test_a_real_production_translation_survives_both_guards(monkeypatch):
    """The live Bangla answer from 2026-10-28, kept verbatim. Its page
    citations are Latin and are supposed to stay, so this pins the
    measurement that the guards reject nothing that reaches users today."""
    real = (
        "বাংলাদেশে গাডো সমুহের ছেলে-মহিলা গোষ্ঠী গাডো ভাষাকে বলা হয়। "
        "(Source: Page 5)\nগাড়ো জাতির মাঝে বেশকে দুইভাষা বলা হয়, কারণ তারা "
        "বাংলা ও ছেলে ঘরের ভাষা দুই ভাষায় সম্বাদন করতে হয়। (Source: Page 1)"
    )
    _llm_returns(monkeypatch, real)

    assert _synth().translate_answer(
        "The Garo language is spoken among the Garo community members in "
        "Bangladesh. (Source: Page 5) The majority of Garo people are "
        "bilingual as they need to communicate in both Bengali and their "
        "native Garo language. (Source: Page 1)",
        "bn",
    ) == real


# --------------------------------------------- Refusals are not translated
#
# KNOWN_LIMITATIONS 29 recorded all three Hindi refusals rendering `मujhe`
# -- Latin letters spliced into Devanagari mid-word. That is not a typo in
# the file: `_NO_EVIDENCE_MESSAGES["hi"]` is clean Devanagari and was never
# being sent. `answer_translations` computed the ENGLISH refusal and put it
# through the model like any other answer, so what a reader saw was
# mistral:7b translating "I could not find enough connected evidence".
#
# Every refusal path returns the same English string -- no triples at all
# (`rag.py:1825`), the relevance gate refusing (`NO_GROUNDED_ANSWER_MESSAGE`,
# `rag.py:1902`), and a fallback with nothing formattable (`rag.py:2058`) --
# so one comparison catches all three.


def _count_llm_calls(monkeypatch, response="RELEVANT: yes\nAn answer."):
    prompts = []

    def fake_post(url, json, timeout=None, headers=None):
        prompts.append(json["prompt"])
        return _Response(response)

    monkeypatch.setattr(rag.requests, "post", fake_post)
    return prompts


def test_a_refusal_reaches_the_reader_in_their_own_script(monkeypatch):
    """The project's own Bangla and Hindi refusals, served as written."""
    _count_llm_calls(monkeypatch)

    translations = _synth().answer_translations(
        "Where do the Garo live?", [], selected_language="bn"
    )

    assert translations["bn"] == rag._NO_EVIDENCE_MESSAGES["bn"]
    assert translations["hi"] == rag._NO_EVIDENCE_MESSAGES["hi"]
    assert translations["en"] == rag._NO_EVIDENCE_MESSAGES["en"]


def test_a_refusal_costs_no_model_calls(monkeypatch):
    """The cheapest win against limitation 28: a refusal that already knows
    its own wording in all three languages has nothing to generate."""
    prompts = _count_llm_calls(monkeypatch)

    _synth().answer_translations(
        "Where do the Garo live?", [], selected_language="bn"
    )

    assert prompts == []


def test_a_gate_refusal_is_served_statically_too(monkeypatch):
    """Evidence was retrieved and the gate judged it irrelevant. The answer
    is still a refusal, so it is still not translated -- only the one
    synthesis call should happen."""
    prompts = _count_llm_calls(monkeypatch, response="RELEVANT: no")

    translations = _synth().answer_translations(
        "What is the Garo population?", [_triple()], selected_language="hi"
    )

    assert translations["hi"] == rag._NO_EVIDENCE_MESSAGES["hi"]
    assert len(prompts) == 1


def test_a_real_answer_is_still_translated(monkeypatch):
    """The guard that keeps the one above honest: a grounded answer must
    still go through the model for each language."""
    prompts = _count_llm_calls(monkeypatch)

    translations = _synth().answer_translations(
        "Where do the Garo live?", [_triple()], selected_language="bn"
    )

    assert translations["bn"] != rag._NO_EVIDENCE_MESSAGES["bn"]
    # one synthesis, plus one translation per language
    assert len(prompts) == 3


def test_the_completeness_guard_runs_on_the_local_provider(monkeypatch):
    """The guards were ported gated on `provider == "llm"`. Switching the
    deployment to the local NLLB path would have silently stopped them, so
    the gate names every provider that needs them rather than the one that
    happened to be deployed when they were written. `online` and `auto` are
    excluded on purpose: online_translate applies them internally."""
    monkeypatch.setenv("TRANSLATION_PROVIDER", "local")
    english = (
        "The Garo people primarily reside in the Garo Hills, Meghalaya, "
        "India, and in Mymensingh, Bangladesh."
    )
    monkeypatch.setattr("local_translation.translate_local",
                        lambda text, source, target: english)

    assert _synth().translate_answer(english, "bn") == ""


def test_numbers_are_restored_on_the_local_provider(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "local")
    monkeypatch.setattr("local_translation.translate_local",
                        lambda text, source, target: "গাড়ো জনসংখ্যা ৩০০, ০০০, ০০০ জন।")

    translated = _synth().translate_answer(
        "The Garo population is 3 million people.", "bn"
    )

    assert "৩০ লাখ" in translated


def test_the_online_path_is_not_guarded_twice(monkeypatch):
    """online_translate already runs both guards inside itself, so the
    provider check must leave that path alone."""
    monkeypatch.setenv("TRANSLATION_PROVIDER", "online")
    monkeypatch.setattr(rag, "online_translate",
                        lambda text, source, target: "গারো জাতি।")

    # A five-word source against a two-word translation: the completeness
    # guard would reject this if it ran here.
    assert _synth().translate_answer(
        "The Garo people live in Mymensingh, Bangladesh, and in Meghalaya.",
        "bn",
    ) == "গারো জাতি।"


# ---------------------------------------------------------------- Google path

def test_local_is_the_default_provider(monkeypatch):
    monkeypatch.delenv("TRANSLATION_PROVIDER", raising=False)
    assert rag.translation_provider() == "local"
    monkeypatch.setenv("TRANSLATION_PROVIDER", "nonsense")
    assert rag.translation_provider() == "local"
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
            return " ".join(["শব্দ"] * len(text.split()))

    monkeypatch.setattr(deep_translator, "GoogleTranslator", Recorder)
    long_text = "\n\n".join(["word " * 600] * 3)  # ~9000 chars
    result = rag.google_translate(long_text, "en", "bn")
    assert len(result.split()) == 1800  # every word came back
    assert max(sizes) <= 4500


# ------------------------------------------------------------------ auto path

def test_auto_never_lets_the_local_model_write_a_bangla_answer(monkeypatch):
    # mistral:7b misspells Bangla, so in auto mode a failed online answer
    # translation shows English with a note. The question may still be
    # translated by the model, since only its English meaning is used.
    monkeypatch.setenv("TRANSLATION_PROVIDER", "auto")
    # Not testing the relevance gate here; disable it so the fake English
    # synthesis response (no "RELEVANT:" marker) isn't treated as a refusal.
    monkeypatch.setenv("SYNTHESIS_RELEVANCE_GATE", "0")
    monkeypatch.setattr(rag, "google_translate", lambda *a: "")
    prompts = []

    def fake_post(url, json, timeout, headers=None):
        prompts.append(json["prompt"])
        if json["prompt"].startswith("Translate this question"):
            return _Response("Where do the Garo live?")
        if json["prompt"].startswith("Translate the following text"):
            pytest.fail("auto mode must not ask the local model for a Bangla answer")
        return _Response("The Garo live in Mymensingh.")

    monkeypatch.setattr(rag.requests, "post", fake_post)
    synth = _synth()
    english_q = synth.english_question("গারোরা কোথায় বাস করে?", "bn")
    assert english_q == "Where do the Garo live?"
    answer = synth.answer("গারোরা কোথায় বাস করে?", [_triple()], "bn", english_q)
    assert answer.startswith(rag._ENGLISH_ONLY_NOTES["bn"])
    assert answer.endswith("The Garo live in Mymensingh.")


def test_llm_mode_still_uses_the_local_model_and_fixes_names(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "llm")
    # Same reason as the auto test above: the fake English synthesis
    # response carries no "RELEVANT:" marker, so with the gate on it is
    # read as a refusal and this ends up testing the translation of a
    # refusal message rather than of an answer. That went unnoticed until
    # the SCRUM-318 completeness guard reached this path and measured the
    # canned five-word Bangla against the twenty-word refusal.
    monkeypatch.setenv("SYNTHESIS_RELEVANCE_GATE", "0")

    def fake_post(url, json, timeout, headers=None):
        if json["prompt"].startswith("Translate the following text"):
            return _Response("মান্ডি মানুষ ময়মনসিংহে বাস করে।")
        return _Response("The Mandi live in Mymensingh.")

    monkeypatch.setattr(rag.requests, "post", fake_post)
    synth = _synth()
    assert synth.answer("x", [_triple()], "bn", "Where do the Mandi live?") \
        == "মান্দি মানুষ ময়মনসিংহে বাস করে।"


def test_a_translated_refusal_is_not_mistaken_for_an_incomplete_answer():
    """The no-evidence message is 20 English words and its Bangla and Hindi
    forms are 22 and 25, so a faithful refusal clears the completeness
    guard. Worth pinning: refusals are short, and a lower threshold would
    start replacing them with English behind a note."""
    english = rag._NO_EVIDENCE_MESSAGES["en"]

    for language in ("bn", "hi"):
        assert not rag.translation_incomplete(
            english, rag._NO_EVIDENCE_MESSAGES[language], language
        )


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


def test_answer_translations_prepare_switchable_language_variants(monkeypatch):
    monkeypatch.setenv("TRANSLATION_PROVIDER", "llm")
    synth = _synth()
    monkeypatch.setattr(
        synth,
        "answer",
        lambda question, triples, language="en", english_question=None: (
            "The Garo people live in Bangladesh."
        ),
    )
    monkeypatch.setattr(
        synth,
        "translate_answer",
        lambda answer, language: f"{language}: translated answer",
    )

    translations = synth.answer_translations(
        "Where do the Garo people live?",
        [_triple()],
        english_question="Where do the Garo people live?",
    )

    assert translations == {
        "en": "The Garo people live in Bangladesh.",
        "hi": "hi: translated answer",
        "bn": "bn: translated answer",
    }


def test_mymemory_uses_its_language_codes_and_splits_long_text(monkeypatch):
    import deep_translator
    _FakeMyMemory.calls = []
    _FakeMyMemory.reply = "এটি গারো মানুষদের সম্পর্কে একটি বাক্য। " * 10
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


def test_mymemory_retries_after_a_short_transient_failure(monkeypatch):
    import deep_translator

    now = [100.0]
    calls = []

    class TemporarilyUnavailable:
        def __init__(self, **kwargs):
            pass

        def translate(self, text):
            calls.append(text)
            raise requests.ConnectionError("temporary network failure")

    monkeypatch.setattr(deep_translator, "MyMemoryTranslator", TemporarilyUnavailable)
    monkeypatch.setattr(rag.time, "time", lambda: now[0])
    monkeypatch.setattr(rag, "_mymemory_blocked_until", 0.0)

    assert _real_mymemory_translate("hello", "en", "bn") == ""
    first_retry = rag._mymemory_blocked_until
    assert first_retry == now[0] + rag.MYMEMORY_TRANSIENT_COOLDOWN_SECONDS

    now[0] = first_retry + 1
    assert _real_mymemory_translate("hello again", "en", "bn") == ""
    assert calls == ["hello", "hello again"]


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


# ----------------------------------------------- skipped words and spelling

def test_split_never_cuts_inside_a_word():
    text = ("Garo households in Madhupur depend on forest land " * 20).strip()
    pieces = rag._split_for_limit(text, 60)
    assert all(len(p) <= 60 for p in pieces)
    assert " ".join(pieces).split() == text.split()


def test_incomplete_translations_are_detected():
    source = "The Garo people mainly live in Mymensingh, Tangail and Sherpur."
    full = "গারো জনগোষ্ঠী প্রধানত ময়মনসিংহ, টাঙ্গাইল এবং শেরপুরে বসবাস করে।"
    assert not rag.translation_incomplete(source, full, "bn")
    assert rag.translation_incomplete(source, "গারো জনগোষ্ঠী।", "bn")  # words dropped
    assert rag.translation_incomplete(source, source, "bn")  # left in English
    assert rag.translation_incomplete(source, "", "bn")
    assert not rag.translation_incomplete("hello", "hello", "en")


def test_google_retries_sentence_by_sentence_when_words_go_missing(monkeypatch):
    import deep_translator
    replies = {
        "The Garo live in Mymensingh. They speak A·chik at home.": "গারোরা।",
        "The Garo live in Mymensingh.": "গারোরা ময়মনসিংহে বাস করে।",
        "They speak A·chik at home.": "তারা বাড়িতে আচিক ভাষায় কথা বলে।",
    }

    class PartialGoogle:
        def __init__(self, **kwargs):
            pass

        def translate(self, text):
            return replies[text]

    monkeypatch.setattr(deep_translator, "GoogleTranslator", PartialGoogle)
    result = rag.google_translate(
        "The Garo live in Mymensingh. They speak A·chik at home.", "en", "bn")
    assert result == "গারোরা ময়মনসিংহে বাস করে। তারা বাড়িতে আচিক ভাষায় কথা বলে।"


def test_google_gives_up_rather_than_return_a_partial_answer(monkeypatch):
    import deep_translator

    class AlwaysPartial:
        def __init__(self, **kwargs):
            pass

        def translate(self, text):
            return "গারো।"

    monkeypatch.setattr(deep_translator, "GoogleTranslator", AlwaysPartial)
    text = "The Garo people mainly live in Mymensingh, Tangail and Sherpur districts."
    assert rag.google_translate(text, "en", "bn") == ""


def test_mymemory_partial_match_is_rejected(monkeypatch):
    import deep_translator
    _FakeMyMemory.calls = []
    _FakeMyMemory.reply = "গারো।"
    monkeypatch.setattr(deep_translator, "MyMemoryTranslator", _FakeMyMemory)
    text = "The Garo people mainly live in Mymensingh, Tangail and Sherpur districts."
    assert _real_mymemory_translate(text, "en", "bn") == ""


def test_online_translation_fixes_project_name_spellings(monkeypatch):
    seen = []

    def fake_google(text, source, target):
        seen.append(text)
        return "মান্ডি জনগণ এ·চিক ভাষায় কথা বলে।"

    monkeypatch.setattr(rag, "google_translate", fake_google)
    result = rag.online_translate("The Mandi people speak A·chik.", "en", "bn")
    assert result == "মান্দি জনগণ আচিক ভাষায় কথা বলে।"
    assert "·" not in seen[0]


def test_english_left_inside_a_bangla_answer_is_translated(monkeypatch):
    translated = (
        "তাদের traditionalঐতিহ্যবাহী ওষুধের অনুশীলন সম্পর্কে। "
        "গারো জনগোষ্ঠীর traditionalঐতিহ্যবাহী medicineষধ অনুশীলন, "
        "এবং ethnobotany গবেষণা। DNA পরীক্ষা।"
    )
    word_calls = []

    def fake_google(text, source, target):
        if text == "ethnobotany":
            word_calls.append(text)
            return "নৃ-উদ্ভিদবিজ্ঞান"
        return translated

    monkeypatch.setattr(rag, "google_translate", fake_google)
    result = rag.online_translate("English answer.", "en", "bn")
    assert result == (
        "তাদের ঐতিহ্যবাহী ওষুধের অনুশীলন সম্পর্কে। "
        "গারো জনগোষ্ঠীর ঐতিহ্যবাহী ওষুধ অনুশীলন, "
        "এবং নৃ-উদ্ভিদবিজ্ঞান গবেষণা। DNA পরীক্ষা।"
    )
    assert word_calls == ["ethnobotany"]  # one lookup per unknown word


def test_untranslatable_english_word_is_kept_not_lost(monkeypatch):
    monkeypatch.setattr(rag, "google_translate", lambda text, s, t: "")
    assert rag.fill_leftover_english("গারো xyzzy শব্দ", "bn") == "গারো xyzzy শব্দ"


def test_bangla_thousands_lose_the_extra_space():
    assert rag.fix_bangla_spelling("জনসংখ্যা ৩০০, ০০০, ০০০।") == "জনসংখ্যা ৩০০,০০০,০০০।"
    assert rag.fix_bangla_spelling("১, ২ এবং ৩") == "১, ২ এবং ৩"


def test_translation_keeps_the_exact_english_numbers(monkeypatch):
    monkeypatch.setattr(rag, "google_translate",
                        lambda text, s, t: "গারো জনসংখ্যা ৩০০, ০০০, ০০০। ২০১১ সালে।")
    result = rag.online_translate(
        "The Garo people population 3000000. In 2011.", "en", "bn")
    assert result == "গারো জনসংখ্যা ৩০০০০০০। ২০১১ সালে।"


def test_numbers_are_left_alone_when_counts_differ():
    assert rag.restore_numbers("1 and 2", "শুধু ৩", "bn") == "শুধু ৩"


def test_sentence_with_english_inside_is_translated_again(monkeypatch):
    source = "They speak Mandi. They have a strong sense of identity."
    calls = []

    def fake_google(text, s, t):
        calls.append(text)
        if text == source:
            return "তারা মান্দি ভাষায় কথা বলে। তাদের পরিচয়ের দৃ strong় ধারণা রয়েছে।"
        if text == "They have a strong sense of identity.":
            return "তাদের পরিচয়ের দৃঢ় ধারণা রয়েছে।"
        return ""

    monkeypatch.setattr(rag, "google_translate", fake_google)
    assert rag.online_translate(source, "en", "bn") == \
        "তারা মান্দি ভাষায় কথা বলে। তাদের পরিচয়ের দৃঢ় ধারণা রয়েছে।"
    assert calls == [source, "They have a strong sense of identity."]


def test_broken_word_is_repaired_when_the_retry_does_not_help(monkeypatch):
    monkeypatch.setattr(rag, "google_translate",
                        lambda text, s, t: "তাদের পরিচয়ের দৃ strong় ধারণা রয়েছে।")
    assert rag.online_translate("They have a strong sense of identity.", "en", "bn") == \
        "তাদের পরিচয়ের দৃঢ় ধারণা রয়েছে।"


def test_normal_repeated_syllables_are_not_merged(monkeypatch):
    monkeypatch.setattr(rag, "google_translate", lambda text, s, t: "সে সেখানে থাকে।")
    assert rag.online_translate("She lives there.", "en", "bn") == "সে সেখানে থাকে।"


def test_million_and_billion_become_lakh_and_crore():
    fix = rag.fix_bangla_spelling
    assert fix("জনসংখ্যা প্রায় ৩ মিলিয়ন এবং") == "জনসংখ্যা প্রায় ৩০ লাখ এবং"
    assert fix("১.৫ মিলিয়ন মানুষ") == "১৫ লাখ মানুষ"
    assert fix("12 মিলিয়ন") == "১ কোটি ২০ লাখ"
    assert fix("২ বিলিয়ন ডলার") == "২০০ কোটি ডলার"
    assert fix("এক মিলিয়ন মানুষ") == "১০ লাখ মানুষ"
    assert fix("কয়েক মিলিয়ন") == "কয়েক ১০ লাখ"


def test_english_terms_in_bangla_letters_are_translated():
    fix = rag.fix_bangla_spelling
    assert fix("ক্লাইমেট চেঞ্জ এই লোকের জন্য") == "জলবায়ু পরিবর্তন এই লোকের জন্য"
    assert fix("ক্লাইমেট চেঞ্জের ইন্ডিজেনাস কমিউনিটি") == "জলবায়ু পরিবর্তনের আদিবাসী সম্প্রদায়"


def test_amounts_with_unit_words_are_compared_as_a_whole():
    restore = rag.restore_numbers
    # Already right in Bangla wording: kept.
    assert restore("About 3000000 people.", "প্রায় ৩০ লাখ মানুষ।", "bn") == "প্রায় ৩০ লাখ মানুষ।"
    assert restore("About 3 million people.", "প্রায় ৩০ লাখ মানুষ।", "bn") == "প্রায় ৩০ লাখ মানুষ।"
    # Wrong amount: replaced, never "৩০০০০০০ লাখ".
    assert restore("About 3000000 people.", "প্রায় ৩০০ লাখ মানুষ।", "bn") == "প্রায় ৩০০০০০০ মানুষ।"
    assert restore("About 3 million people.", "প্রায় ৩ লাখ মানুষ।", "bn") == "প্রায় ৩০ লাখ মানুষ।"
    # Years and plain numbers still work as before.
    assert restore("In 2011.", "২০১২ সালে।", "bn") == "২০১১ সালে।"


def test_one_leftover_english_word_is_not_mostly_english():
    source = "They practise ethnobotany in the hills."
    assert not rag.translation_incomplete(source, "তারা পাহাড়ে ethnobotany চর্চা করে।", "bn")
    assert rag.translation_incomplete(source, source, "bn")


@pytest.mark.parametrize("success", [True, False])
def test_default_local_provider_never_uses_online_or_ollama(monkeypatch, success):
    import local_translation
    monkeypatch.delenv("TRANSLATION_PROVIDER", raising=False)
    calls = []

    def local(text, source, target):
        # Language-aware since 2026-10-28: the completeness guard now runs on
        # the local provider too, and it is right to reject an all-English
        # string offered as a Hindi answer. The question direction still
        # returns English, because that is what bn->en produces.
        calls.append((source, target))
        if not success:
            return ""
        return "translated test" if target == "en" else "अनूदित उत्तर"

    def forbidden(*args, **kwargs):
        pytest.fail("Local translation must not call an online or Ollama translator")

    monkeypatch.setattr(local_translation, "translate_local", local)
    monkeypatch.setattr(rag, "online_translate", forbidden)
    synth = _synth()
    monkeypatch.setattr(synth, "_llm_translate", forbidden)
    question = "পরীক্ষার প্রশ্ন"
    assert synth.translate_question(question, "bn") == ("translated test" if success else question)
    assert synth.translate_answer("Fictional answer.", "hi") == ("अनूदित उत्तर" if success else "")
    assert calls == [("bn", "en"), ("en", "hi")]


@pytest.mark.parametrize("language", ["bn", "hi"])
def test_local_translation_failure_falls_back_without_an_online_call(
    monkeypatch, language
):
    """The privacy guarantee is the point of this test and is unchanged:
    a local-provider failure must NEVER reach a third-party translator
    (`forbidden` below fails the test if it does).

    What changed on 2026-10-28 is the user-visible result. This used to be
    a 503 with no answer at all; it is now the English answer behind a
    note. The online call is still forbidden either way.
    """
    import local_translation

    monkeypatch.setenv("TRANSLATION_PROVIDER", "local")
    monkeypatch.setattr(
        local_translation, "translate_local", lambda *args: ""
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Local failure must not call an online translator")

    monkeypatch.setattr(rag, "online_translate", forbidden)
    synthesizer = _synth()
    monkeypatch.setattr(
        synthesizer, "answer",
        lambda *args, **kwargs: "Fictional English answer."
    )

    response = _post(
        create_query_handler(_FakeSkeleton(), synthesizer),
        {"query": "Fictional test question?", "language": language},
    )

    assert response["status"] == 200
    assert response["payload"]["language"] == language
    assert response["payload"]["answer"].startswith(
        rag._ENGLISH_ONLY_NOTES[language]
    )
    assert "Fictional English answer." in response["payload"]["answer"]
    # Nothing about the online services may leak into what a user reads.
    assert "MYMEMORY_EMAIL" not in response["payload"]["answer"]
