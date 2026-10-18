import unittest
from unittest.mock import patch
import local_translation as local


class Tokenizer:
    def encode(self, text, add_special_tokens=True):
        return list(text) + [0, 1]


class LocalTests(unittest.TestCase):
    def test_long_input_is_covered_without_truncation(self):
        text = 'word ' * 200
        chunks = list(local._chunks(text, Tokenizer(), limit=32))
        self.assertGreater(len(chunks), 1)
        self.assertEqual(' '.join(' '.join(chunks).split()), ' '.join(text.split()))
        self.assertTrue(all(len(Tokenizer().encode(c)) <= 32 for c in chunks))

    def test_blank_paragraph_is_retained(self):
        self.assertEqual(list(local._chunks('First.\n\nLast.', Tokenizer())), ['First.', None, 'Last.'])

    def test_failure_returns_no_partial_translation(self):
        with patch.object(local, '_load_engine', side_effect=OSError('private text')):
            with patch('builtins.print') as log:
                self.assertEqual(local.translate_local('private text', 'en', 'bn'), '')
                self.assertNotIn('private text', str(log.call_args))

    def test_english_identity_does_not_load_model(self):
        with patch.object(local, '_load_engine') as load:
            self.assertEqual(local.translate_local('Test.', 'en', 'en'), 'Test.')
            load.assert_not_called()
