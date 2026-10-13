enum MessageAuthor { user, assistant }

enum MessageFeedback { helpful, notHelpful }

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

  Map<String, dynamic> toJson() => {
    'subject': subject,
    'predicate': predicate,
    'object': object,
    'sentence_ref': sentenceRef,
    'source_section': sourceSection,
    'passage': passage,
    'confidence': confidence,
  };

  String get triple => '$subject — $predicate → $object';

  String get supportingText => sentenceRef.isNotEmpty ? sentenceRef : passage;
}

// Stores one rendered turn together with its sources and optional feedback.
class ChatMessage {
  const ChatMessage({
    required this.text,
    required this.author,
    this.sources = const [],
    this.translations = const {},
    this.feedback,
    this.feedbackComment = '',
  });

  final String text;
  final MessageAuthor author;
  final List<SourceEvidence> sources;
  final Map<String, String> translations;
  final MessageFeedback? feedback;
  final String feedbackComment;

  String textFor(String languageCode) => translations[languageCode] ?? text;

  // False when [languageCode] has no translation, so [textFor] falls back to
  // the language the question was originally answered in. Messages without
  // any translations (user questions, errors) are never flagged.
  bool hasTextFor(String languageCode) =>
      translations.isEmpty || translations.containsKey(languageCode);

  // The language [textFor] actually returns for [languageCode]: the selected
  // language when a translation exists, otherwise the original answer's.
  String displayLanguageFor(String languageCode) {
    if (hasTextFor(languageCode)) return languageCode;
    for (final entry in translations.entries) {
      if (entry.value == text) return entry.key;
    }
    return languageCode;
  }

  ChatMessage copyWith({
    MessageFeedback? feedback,
    String? feedbackComment,
    Map<String, String>? translations,
  }) {
    return ChatMessage(
      text: text,
      author: author,
      sources: sources,
      translations: translations ?? this.translations,
      feedback: feedback ?? this.feedback,
      feedbackComment: feedbackComment ?? this.feedbackComment,
    );
  }

  Map<String, dynamic> toJson() => {
    'text': text,
    'author': author.name,
    'sources': sources.map((source) => source.toJson()).toList(),
    'translations': translations,
    'feedback': feedback?.name,
    'feedback_comment': feedbackComment,
  };

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    final author = json['author'] == MessageAuthor.user.name
        ? MessageAuthor.user
        : MessageAuthor.assistant;

    final sources = <SourceEvidence>[];
    final rawSources = json['sources'];

    if (rawSources is List) {
      for (final item in rawSources) {
        if (item is Map) {
          sources.add(SourceEvidence.fromJson(Map<String, dynamic>.from(item)));
        }
      }
    }

    MessageFeedback? feedback;
    final rawFeedback = json['feedback'];

    if (rawFeedback == MessageFeedback.helpful.name) {
      feedback = MessageFeedback.helpful;
    } else if (rawFeedback == MessageFeedback.notHelpful.name) {
      feedback = MessageFeedback.notHelpful;
    }

    final translations = <String, String>{};
    final rawTranslations = json['translations'];
    if (rawTranslations is Map) {
      for (final entry in rawTranslations.entries) {
        if (entry.key is String && entry.value is String) {
          translations[entry.key as String] = entry.value as String;
        }
      }
    }

    return ChatMessage(
      text: json['text'] as String? ?? '',
      author: author,
      sources: sources,
      translations: translations,
      feedback: feedback,
      feedbackComment: json['feedback_comment'] as String? ?? '',
    );
  }
}
