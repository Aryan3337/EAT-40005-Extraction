import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_application/models/chat_message.dart';

void main() {
  test('source metadata survives chat history serialization', () {
    final message = ChatMessage(
      text: 'Answer',
      author: MessageAuthor.assistant,
      sources: [
        SourceEvidence.fromJson({
          'paper_title': 'Recorded paper title',
          'page_number': 12,
          'source_file': 'paper.pdf',
          'source_type': 'research_paper',
        }),
      ],
    );
    final restored = ChatMessage.fromJson(message.toJson()).sources.single;
    expect(restored.paperTitle, 'Recorded paper title');
    expect(restored.recordedPage, '12');
    expect(restored.sourceFile, 'paper.pdf');
    expect(restored.sourceTypeLabelKey, 'researchPaper');
  });

  test('legacy page markers work but section numbers are not pages', () {
    expect(
      SourceEvidence.fromJson({'source_section': 'Page 4'}).recordedPage,
      '4',
    );
    expect(
      SourceEvidence.fromJson({'source_section': 'Section 4'}).recordedPage,
      '',
    );
    expect(SourceEvidence.fromJson({}).sourceTypeLabelKey, 'unknownSourceType');
    expect(
      SourceEvidence.fromJson({'source_type': 'community_data'})
          .sourceTypeLabelKey,
      'communityData',
    );
  });
}
