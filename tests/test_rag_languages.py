import unittest
from unittest.mock import Mock, patch

from rag import AnswerSynthesizer


class AnswerLanguageTests(unittest.TestCase):
    def test_non_english_question_is_translated_for_graph_search(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "response": "Where do the Garo people live?"
        }

        with patch("rag.requests.post", return_value=response) as post:
            translated = AnswerSynthesizer().translate_question(
                "¿Dónde vive el pueblo Garo?",
                "es",
            )

        self.assertEqual(translated, "Where do the Garo people live?")
        prompt = post.call_args.kwargs["json"]["prompt"]
        self.assertIn("Translate this question from Spanish into English", prompt)
        self.assertIn("¿Dónde vive el pueblo Garo?", prompt)

    def test_prompt_requests_the_selected_answer_language(self):
        for language, expected_name in (
            ("en", "English"),
            ("es", "Spanish"),
            ("fr", "French"),
            ("hi", "Hindi"),
            ("zh", "Mandarin Chinese"),
        ):
            with self.subTest(language=language):
                prompt = AnswerSynthesizer()._build_prompt(
                    "Where do they live?", [], language
                )
                self.assertIn(f"entire answer in {expected_name}", prompt)

    def test_empty_graph_answers_are_localized(self):
        expected_phrases = {
            "en": "I could not find enough connected evidence",
            "es": "No encontré suficiente evidencia",
            "fr": "Je n’ai pas trouvé suffisamment",
            "hi": "पर्याप्त जुड़ी हुई जानकारी",
            "zh": "没有找到足够相关的信息",
        }
        for language, expected_phrase in expected_phrases.items():
            with self.subTest(language=language):
                answer = AnswerSynthesizer().answer("Question", [], language)
                self.assertIn(expected_phrase, answer)

    def test_unknown_response_language_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported language"):
            AnswerSynthesizer().answer("Question", [], "de")

    def test_fallback_answers_use_the_selected_language(self):
        expected_fragments = {
            "en": ("Based on the available knowledge", "Garo people live in Meghalaya"),
            "es": ("Según la información disponible", "pueblo Garo vive en Meghalaya"),
            "fr": ("D’après les informations disponibles", "peuple Garo vit à Meghalaya"),
            "hi": ("उपलब्ध जानकारी के आधार पर", "गारो लोग Meghalaya में रहते हैं"),
            "zh": ("根据现有信息", "加罗人居住在Meghalaya"),
        }
        triple = {
            "subject": "GaroCommunity",
            "predicate": "LIVE_IN",
            "object": "Meghalaya",
        }
        for language, (expected_intro, expected_fact) in expected_fragments.items():
            with self.subTest(language=language):
                answer = AnswerSynthesizer()._fallback_answer([triple], language)
                self.assertIn(expected_intro, answer)
                self.assertIn(expected_fact, answer)


if __name__ == "__main__":
    unittest.main()
