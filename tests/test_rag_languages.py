"""Answer-language behaviour, parameterised over the languages we ship.

These tests replace nine failures that had been failing for a while and were
not defects. The old file hardcoded `en/es/fr/hi/zh`, the set
`ANSWER_LANGUAGES` held when it was written. es/fr/zh were later dropped and
`bn` added, so the assertions were checking languages the system no longer
serves while never checking the one it does.

**So nothing here names a language literally in a loop.** Every case is
driven from `ANSWER_LANGUAGES` or `_NO_EVIDENCE_MESSAGES`, which is what
`normalize_language` screens against. Adding or dropping a language changes
what these tests cover automatically instead of silently invalidating them.
English wording is anchored with one literal per behaviour so the
table-driven cases cannot pass by comparing the code to itself.
"""

import unittest
from unittest.mock import Mock, patch

from rag import (
    ANSWER_LANGUAGES,
    DEFAULT_LANGUAGE,
    _NO_EVIDENCE_MESSAGES,
    AnswerSynthesizer,
)


class AnswerLanguageTests(unittest.TestCase):
    def test_non_english_question_is_translated_for_graph_search(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"response": "Where do the Garo people live?"}

        # Pin the provider: the default is "local" (NLLB in-process), which
        # never calls rag.requests.post. This exercises the llm provider.
        with patch("rag.translation_provider", return_value="llm"):
            with patch("rag.requests.post", return_value=response) as post:
                translated = AnswerSynthesizer().translate_question(
                    "गारो लोग कहाँ रहते हैं?", "hi"
                )

        self.assertEqual(translated, "Where do the Garo people live?")
        prompt = post.call_args.kwargs["json"]["prompt"]
        self.assertIn("Translate this question from Hindi into English", prompt)
        self.assertIn("गारो लोग कहाँ रहते हैं?", prompt)

    def test_a_plain_english_question_is_not_sent_for_translation(self):
        # _is_plain_english short-circuits before any provider is consulted.
        with patch("rag.requests.post") as post:
            translated = AnswerSynthesizer().translate_question(
                "Where do the Garo live?", "hi"
            )
        self.assertEqual(translated, "Where do the Garo live?")
        post.assert_not_called()

    def test_prompt_requests_the_selected_answer_language(self):
        for language, expected_name in ANSWER_LANGUAGES.items():
            with self.subTest(language=language):
                prompt = AnswerSynthesizer()._build_prompt(
                    "Where do they live?", [], language
                )
                self.assertIn(f"entire answer in {expected_name}", prompt)

    def test_prompt_names_english_for_the_default_language(self):
        # The literal that stops the loop above being a tautology.
        prompt = AnswerSynthesizer()._build_prompt("Where do they live?", [], "en")
        self.assertIn("Write the entire answer in English", prompt)

    def test_empty_graph_answers_are_localized(self):
        synthesizer = AnswerSynthesizer()
        for language in ANSWER_LANGUAGES:
            with self.subTest(language=language):
                self.assertEqual(
                    synthesizer.answer("Question", [], language),
                    _NO_EVIDENCE_MESSAGES[language],
                )

    def test_the_english_refusal_says_what_it_has_always_said(self):
        # Anchors the wording the loop above compares against.
        self.assertIn(
            "I could not find enough connected evidence",
            AnswerSynthesizer().answer("Question", [], "en"),
        )

    def test_an_unsupported_language_falls_back_to_english(self):
        # Replaces test_unknown_response_language_is_rejected, which asserted
        # a ValueError. That contract was deliberately replaced by
        # normalize_language: answer() normalizes first, so an unsupported
        # code becomes DEFAULT_LANGUAGE and cannot reach a raise. The rejection
        # it tested is now unreachable (see rag.py:1649).
        self.assertEqual(
            AnswerSynthesizer().answer("Question", [], "de"),
            _NO_EVIDENCE_MESSAGES[DEFAULT_LANGUAGE],
        )

    def test_fallback_answers_carry_the_facts_in_every_supported_language(self):
        triple = {
            "subject": "GaroCommunity",
            "predicate": "LIVE_IN",
            "object": "Meghalaya",
        }
        synthesizer = AnswerSynthesizer()
        for language in ANSWER_LANGUAGES:
            with self.subTest(language=language):
                answer = synthesizer._fallback_answer([dict(triple)], language)
                # The object survives in every language: the templates
                # translate the sentence frame, not the entity names.
                self.assertIn("Meghalaya", answer)

    def test_the_english_fallback_reads_as_a_sentence(self):
        answer = AnswerSynthesizer()._fallback_answer(
            [{"subject": "GaroCommunity", "predicate": "LIVE_IN", "object": "Meghalaya"}],
            "en",
        )
        self.assertIn("Based on the available knowledge", answer)
        self.assertIn("Garo people live in Meghalaya", answer)

    def test_hindi_fallback_uses_hindi_prose(self):
        # Hindi has real reviewed templates, so assert it actually uses them
        # rather than quietly falling through to the English frame.
        answer = AnswerSynthesizer()._fallback_answer(
            [{"subject": "GaroCommunity", "predicate": "LIVE_IN", "object": "Meghalaya"}],
            "hi",
        )
        self.assertIn("उपलब्ध जानकारी के आधार पर", answer)
        self.assertIn("Meghalaya", answer)


if __name__ == "__main__":
    unittest.main()
