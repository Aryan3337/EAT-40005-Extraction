import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import unittest
from community_candidates import candidate

class CandidateTests(unittest.TestCase):
    def test_context_and_verbatim_response_survive(self):
        r = dict(context_kind='month', row_context='DemoMonth',
                 column_headers=['Which crops are harvested'], response='Demo A, Demo B',
                 source_section='Table 2, row 2, columns [3]',
                 source_file='fictional.docx',record_id='demo')
        c = candidate(r, 1)
        self.assertEqual(c['object'], r['response'])
        self.assertIn('DemoMonth', c['sentence_ref'])
        self.assertIn(r['column_headers'][0], c['sentence_ref'])
        self.assertEqual(c['review_status'], 'candidate')
        self.assertEqual(c['page_number'], '')
        self.assertEqual(c['source_type'], 'community_data')

if __name__ == '__main__': unittest.main()
