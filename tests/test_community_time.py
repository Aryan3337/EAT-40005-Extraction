import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import unittest
from community_time import filter_community_periods, period_from_heading

class PeriodTests(unittest.TestCase):
    def setUp(self):
        self.rows=[dict(source_type='community_data',time_period=p) for p in
                   ['50_60_years_ago','10_20_years_ago','current','']]
    def test_each_period_is_isolated(self):
        for q,p in [('50/60 years ago','50_60_years_ago'),
                    ('10/20 years ago','10_20_years_ago'),('now','current')]:
            self.assertEqual([r['time_period'] for r in filter_community_periods(self.rows,q)],[p])
    def test_no_period_does_not_filter(self):
        self.assertEqual(filter_community_periods(self.rows,'wildlife'),self.rows)
    def test_comparison_preserves_both_periods(self):
        self.assertEqual(len(filter_community_periods(self.rows,'Compare 50/60 years ago and now')),2)
    def test_no_false_period_assignment(self):
        self.assertEqual(period_from_heading('Current natural disasters'),'')
        self.assertEqual(period_from_heading('What was there 50/60 years ago?'),'50_60_years_ago')

if __name__=='__main__':unittest.main()
