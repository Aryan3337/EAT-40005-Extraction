import unittest
from community_attribution import group_responses

class AttributionTests(unittest.TestCase):
    def test_short_negative_not_ranked_by_response_length(self):
        rows = [dict(source_type='community_data', evidence_kind='narrative',
                     question='1. Changes?', source_file=f'doc{n}', object=value)
                for n, value in [(2, 'Long affirmative'), (3, 'Other affirmative'), (1, 'No.')]]
        self.assertEqual(group_responses(rows, 3)[0]['object'], 'No.')

    def test_zero_limit(self):
        self.assertEqual(group_responses([{}], 0), [])

    def test_research_order_unchanged(self):
        rows = [dict(source_type='research_paper', object=str(i)) for i in range(3)]
        self.assertEqual(group_responses(rows, 2), rows[:2])
