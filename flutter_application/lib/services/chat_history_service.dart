import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../models/chat_conversation.dart';

class ChatHistoryService {
  Future<List<ChatConversation>> load(String email) async {
    final preferences = await SharedPreferences.getInstance();
    final raw = preferences.getString(_keyFor(email));
    if (raw == null) return [];

    try {
      final records = jsonDecode(raw) as List<dynamic>;
      return records
          .whereType<Map<String, dynamic>>()
          .map(ChatConversation.fromJson)
          .where((conversation) => conversation.messages.isNotEmpty)
          .toList()
        ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    } on FormatException {
      return [];
    }
  }

  Future<void> save(String email, List<ChatConversation> conversations) async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(
      _keyFor(email),
      jsonEncode(
        conversations.map((conversation) => conversation.toJson()).toList(),
      ),
    );
  }

  Future<void> delete(String email, String conversationId) async {
    final conversations = await load(email);
    conversations.removeWhere(
      (conversation) => conversation.id == conversationId,
    );
    await save(email, conversations);
  }

  String _keyFor(String email) =>
      'chat.history.${base64Url.encode(utf8.encode(email.toLowerCase()))}';
}
