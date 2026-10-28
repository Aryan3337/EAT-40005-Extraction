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


class _Row(list):
    def tolist(self):
        return list(self)


class _Config:
    eos_token_id = 2


class _FakeTokenizer:
    """Enough of a tokenizer for translate_local: callable, encodes, decodes."""

    def __init__(self):
        self.src_lang = None

    def __call__(self, text, return_tensors=None, truncation=None):
        self.last_text = text
        return {"input_ids": [[1, 2, 3]]}

    def encode(self, text, add_special_tokens=True):
        return list(text) + [0, 1]

    def convert_tokens_to_ids(self, token):
        return 99

    def decode(self, output, skip_special_tokens=True):
        return "অনুবাদ"


class _FakeModel:
    config = _Config()

    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return [_Row([7, 2])]


class _FakeTorch:
    class _Ctx:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    def inference_mode(self):
        return self._Ctx()


class DecodingTests(unittest.TestCase):
    """KNOWN_LIMITATIONS 29, measured 2026-10-28: translating the benchmark
    answers greedily dropped three negations from one sentence, turned
    asthma into a duck and mangled a quoted sentence in Hindi. The same
    model and weights with beam search got all of them right, and was not
    slower -- 4-7s per answer against 2.6-26s greedy."""

    def test_translation_uses_beam_search(self):
        model = _FakeModel()
        engine = (_FakeTokenizer(), model, _FakeTorch())

        with patch.object(local, "_load_engine", return_value=engine):
            local.translate_local("The Garo live in Mymensingh.", "en", "bn")

        self.assertTrue(model.calls, "the model was never asked to generate")
        self.assertEqual(model.calls[0].get("num_beams"), 5)

    def test_greedy_sampling_stays_off(self):
        """Beam search replaces greedy decoding; it must not switch sampling
        on, which would make the same answer translate differently on
        different days."""
        model = _FakeModel()
        engine = (_FakeTokenizer(), model, _FakeTorch())

        with patch.object(local, "_load_engine", return_value=engine):
            local.translate_local("The Garo live in Mymensingh.", "en", "bn")

        self.assertIs(model.calls[0].get("do_sample"), False)


class AbbreviationTests(unittest.TestCase):
    """The same measurement shredded "the seeds of T. indica and S. cumini"
    into three fragments, because the sentence splitter treated the dots in
    "T." and "S." as sentence ends. The Bangla came back as "the seeds of T.
    are used. Indica and S. Cumini in their formulations."."""

    def test_a_single_letter_abbreviation_does_not_end_a_sentence(self):
        text = ("The Mandai TMPs use the seeds of T. indica and S. cumini in "
                "their formulations.")
        chunks = [c for c in local._chunks(text, _FakeTokenizer(), limit=4096)
                  if c]

        self.assertEqual(len(chunks), 1)
        self.assertIn("T. indica and S. cumini", chunks[0])

    def test_real_sentence_ends_still_split(self):
        text = "The Garo live in Mymensingh. They speak Garo. It is declining."
        chunks = [c for c in local._chunks(text, _FakeTokenizer(), limit=4096)
                  if c]

        self.assertEqual(len(chunks), 3)
