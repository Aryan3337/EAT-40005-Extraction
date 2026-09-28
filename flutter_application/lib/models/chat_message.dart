enum MessageAuthor { user, assistant }

// Stores one rendered turn in the conversation.
class ChatMessage {
  const ChatMessage({
    required this.text,
    required this.author,
    this.sources = const [],
    this.facts = const [],
  });

  final String text;
  final MessageAuthor author;
  final List<String> sources;

  // Knowledge-graph facts the RAG backend retrieved to ground this answer.
  final List<String> facts;
}
