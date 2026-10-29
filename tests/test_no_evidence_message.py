"""One refusal message per language, from one table.

`_NO_EVIDENCE_MESSAGES` (module level) and the dict inside
`_no_evidence_message` were written at different times and disagreed: the
first held en/hi/bn, the second en/es/fr/hi/zh with no bn and different
Hindi wording. Nothing in production reached the divergence -- the only
caller of `_fallback_answer` passes DEFAULT_LANGUAGE explicitly (rag.py:2000)
-- so these tests pin a trap shut rather than fix a live fault.
"""

import unittest

from rag import ANSWER_LANGUAGES, _NO_EVIDENCE_MESSAGES, AnswerSynthesizer


class NoEvidenceMessageTests(unittest.TestCase):
    def test_bangla_refusal_does_not_raise(self):
        # Was a KeyError: the inner dict had no "bn" entry at all.
        self.assertEqual(
            AnswerSynthesizer()._no_evidence_message("bn"),
            _NO_EVIDENCE_MESSAGES["bn"],
        )

    def test_every_supported_language_has_one_agreed_wording(self):
        synthesizer = AnswerSynthesizer()
        for language in ANSWER_LANGUAGES:
            with self.subTest(language=language):
                self.assertEqual(
                    synthesizer._no_evidence_message(language),
                    _NO_EVIDENCE_MESSAGES[language],
                )

    def test_unsupported_code_falls_back_to_english_instead_of_raising(self):
        # normalize_language already coerces unknown codes at the API
        # boundary, so this is defence for a direct internal caller.
        self.assertEqual(
            AnswerSynthesizer()._no_evidence_message("de"),
            _NO_EVIDENCE_MESSAGES["en"],
        )

    def test_the_table_covers_exactly_the_supported_languages(self):
        # Stops the two tables drifting apart again: a language added to
        # ANSWER_LANGUAGES without a refusal message fails here.
        self.assertEqual(set(_NO_EVIDENCE_MESSAGES), set(ANSWER_LANGUAGES))


class FallbackLanguageTests(unittest.TestCase):
    """The same missing-`bn` trap, one function along.

    `_format_triple`'s `localized_relation` is keyed es/fr/hi/zh and indexed
    with a hard `[language]`. es/fr/zh can no longer arrive -- normalize_language
    screens them -- and `bn`, which can, is the one key absent, so every
    predicate raised KeyError for Bangla. Latent like the refusal table:
    `_format_triple`'s only caller is `_fallback_answer`, whose only
    production caller passes DEFAULT_LANGUAGE (rag.py:2000).
    """

    TRIPLE = {
        "subject": "GaroCommunity",
        "predicate": "OBSERVES_FESTIVAL",  # deliberately not in any template
        "object": "Wangala",
    }

    def test_every_supported_language_formats_a_triple_without_raising(self):
        synthesizer = AnswerSynthesizer()
        for language in ANSWER_LANGUAGES:
            with self.subTest(language=language):
                sentence = synthesizer._format_triple(dict(self.TRIPLE), language)
                self.assertIn("Wangala", sentence)

    def test_every_supported_language_builds_a_fallback_answer(self):
        synthesizer = AnswerSynthesizer()
        for language in ANSWER_LANGUAGES:
            with self.subTest(language=language):
                answer = synthesizer._fallback_answer([dict(self.TRIPLE)], language)
                self.assertIn("Wangala", answer)


if __name__ == "__main__":
    unittest.main()
