enum MessageAuthor { user, assistant }

// Stores one knowledge-graph record used to verify an assistant response.
class SourceEvidence {
  const SourceEvidence({
    required this.subject,
    required this.predicate,
    required this.object,
    required this.sentenceRef,
    required this.sourceSection,
    required this.passage,
    required this.confidence,
  });

  final String subject;
  final String predicate;
  final String object;
  final String sentenceRef;
  final String sourceSection;
  final String passage;
  final String confidence;

  factory SourceEvidence.fromJson(Map<String, dynamic> json) {
    String read(String key) => json[key]?.toString().trim() ?? '';

    return SourceEvidence(
      subject: read('subject'),
      predicate: read('predicate'),
      object: read('object'),
      sentenceRef: read('sentence_ref'),
      sourceSection: read('source_section'),
      passage: read('passage'),
      confidence: read('confidence'),
    );
  }

  String get triple => '$subject — $predicate → $object';

  String get supportingText => sentenceRef.isNotEmpty ? sentenceRef : passage;
}

// Stores one rendered turn in the conversation.
class ChatMessage {
  const ChatMessage({
    required this.text,
    required this.author,
    this.sources = const [],
  });

  final String text;
  final MessageAuthor author;
  final List<SourceEvidence> sources;
}
