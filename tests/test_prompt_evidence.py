import copy
import unittest
from prompt_evidence import build_prompt_evidence


def record(obj='Language A', **changes):
    result = dict(subject='Example people', predicate='BILINGUAL', object=obj,
                  sentence_ref='People use Language A and Language B.',
                  source_type='research_paper', source_file='example.pdf',
                  paper_title='Example paper', source_section='Page 1', page_number=1)
    result.update(changes)
    return result


class PromptEvidenceTests(unittest.TestCase):
    def test_shared_quote_once_both_facts_and_input_unchanged(self):
        records = [record(), record('Language B')]
        before = copy.deepcopy(records)
        result = build_prompt_evidence(records)
        self.assertEqual(len(result), 1)
        self.assertEqual([f['object'] for f in result[0]['facts']], ['Language A', 'Language B'])
        self.assertEqual(result[0]['source_context'], records[0]['sentence_ref'])
        self.assertEqual(records, before)

    def test_distinct_sources_locations_or_quotes_not_combined(self):
        for change in [dict(source_file='other.pdf'), dict(page_number=2),
                       dict(source_section='Appendix'), dict(paper_title='Other'),
                       dict(sentence_ref='Different wording.')]:
            with self.subTest(change=change):
                self.assertEqual(len(build_prompt_evidence([record(), record(**change)])), 2)

    def test_community_unknown_and_empty_quote_remain_separate(self):
        for change in [dict(source_type='community_data'), dict(source_type=''),
                       dict(sentence_ref=''), dict(source_file='', paper_title='')]:
            with self.subTest(change=change):
                self.assertEqual(len(build_prompt_evidence([record(**change), record(**change)])), 2)

    def test_order_and_all_facts_retained(self):
        result = build_prompt_evidence([record(), record('Other', source_file='other.pdf'), record('Language B')])
        self.assertEqual(len(result), 2)
        self.assertEqual(sum(len(r['facts']) for r in result), 3)

    def test_empty(self):
        self.assertEqual(build_prompt_evidence([]), [])
