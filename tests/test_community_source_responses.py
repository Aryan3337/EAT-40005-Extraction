import unittest
from community_attribution import source_response_answer

class SourceResponseTests(unittest.TestCase):
    def row(self, title, response, question='Any changes?'):
        return dict(source_type='community_data', evidence_kind='narrative',
                    question=question, paper_title=title, object=response)

    def test_disagreement_is_preserved_with_source_labels(self):
        text = source_response_answer([self.row('Community record 01','No.'),
                                      self.row('Community record 02','Trees changed.')])
        self.assertIn('Community record 01: No.', text)
        self.assertIn('Community record 02: Trees changed.', text)
        self.assertIn('Question: Any changes?', text)
        self.assertIn('do not establish agreement', text)

    def test_mixed_questions_do_not_use_source_renderer(self):
        self.assertIsNone(source_response_answer([self.row('One','No.'),
                                                 self.row('Two','Yes.','Different?')]))

    def test_other_evidence_and_empty_input_keep_normal_path(self):
        self.assertIsNone(source_response_answer([]))
        self.assertIsNone(source_response_answer([dict(source_type='research_paper')]))
