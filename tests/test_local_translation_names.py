import unittest
from local_translation import _prepare_names, _names_preserved


class NameTests(unittest.TestCase):
    def test_observed_question(self):
        self.assertEqual(_prepare_names('গারোরা কোন কোন ভাষায় কথা বলে?', 'bn', 'en'),
                         'Garo জনগণ কোন কোন ভাষায় কথা বলে?')

    def test_plural_and_possessive(self):
        self.assertEqual(_prepare_names('গারোদের এবং মান্দিদের', 'bn', 'en'),
                         'Garo জনগণের এবং Mandi জনগণের')
        self.assertEqual(_prepare_names('মান্দিরা', 'bn', 'en'), 'Mandi জনগণ')

    def test_no_substring_replacement(self):
        self.assertEqual(_prepare_names('অগারো গারোভাষা', 'bn', 'en'), 'অগারো গারোভাষা')

    def test_other_directions_unchanged(self):
        self.assertEqual(_prepare_names('Garo people', 'en', 'bn'), 'Garo people')

    def test_germans_or_missing_name_is_rejected(self):
        self.assertFalse(_names_preserved('Garo জনগণ', 'What language do Germans speak?', 'en'))
        self.assertFalse(_names_preserved('Garo and Mandi', 'Garo people', 'en'))

    def test_preserved_names_pass(self):
        self.assertTrue(_names_preserved('Garo জনগণ', 'What language do the Garo people speak?', 'en'))
        self.assertTrue(_names_preserved('Mandi জনগণ', 'What language do Mandi people speak?', 'en'))

    def test_repeated_mentions_and_capitalisation(self):
        self.assertFalse(_names_preserved('Garo Garo', 'Garo', 'en'))
        self.assertTrue(_names_preserved('Garo', 'garo', 'en'))
