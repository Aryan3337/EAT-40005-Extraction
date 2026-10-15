import unittest
from source_provenance import provenance_fields


class ProvenanceTests(unittest.TestCase):
    def test_explicit_metadata_is_preserved(self):
        row = {'paper_title': 'Recorded title', 'source_file': 'paper.pdf',
               'page_number': 12, 'source_type': 'research_paper', 'source_section': 'Page 3'}
        result = provenance_fields(row)
        self.assertEqual(result['page_number'], '12')
        self.assertEqual(result['paper_title'], 'Recorded title')
        self.assertEqual(result['source_type'], 'research_paper')

    def test_page_marker_is_supported(self):
        self.assertEqual(provenance_fields({'source_section': 'Page 3'})['page_number'], '3')

    def test_section_digits_are_not_invented_pages(self):
        for section in ['Section 3', '3.2 Results', 'Unknown', 'Page 0', 'Page 3 and 4']:
            self.assertEqual(provenance_fields({'source_section': section})['page_number'], '')

    def test_missing_metadata_is_not_guessed_from_filename(self):
        result = provenance_fields({'source_file': 'garo_1.pdf'})
        self.assertEqual(result['paper_title'], '')
        self.assertEqual(result['source_type'], '')

    def test_community_data_is_explicit(self):
        self.assertEqual(provenance_fields({'source_type': 'community-data'})['source_type'], 'community_data')
        self.assertEqual(provenance_fields({'source_type': 'other'})['source_type'], '')

    def test_empty_and_null_are_safe(self):
        self.assertEqual(provenance_fields({'page_number': None}),
                         dict(paper_title='', source_file='', page_number='', source_type=''))


if __name__ == '__main__':
    unittest.main()
