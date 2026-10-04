enum MessageAuthor { user, assistant }

// Stores one rendered turn in the conversation.
class ChatMessage {
  const ChatMessage({
    required this.text,
    required this.author,
    //this.sources = const [],
  });

  final String text;
  final MessageAuthor author;
  //final List<String> sources;

  Map<String, dynamic> toJson() => {'text': text, 'author': author.name};

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    final author = json['author'] == MessageAuthor.user.name
        ? MessageAuthor.user
        : MessageAuthor.assistant;
    return ChatMessage(text: json['text'] as String? ?? '', author: author);
  }
}
