import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../models/chat_conversation.dart';
import 'api_config.dart';

class ChatHistoryService {
  ChatHistoryService({
    http.Client? client,
    String? endpoint,
    this.authToken,
    bool? persistHistory,
  }) : _persistHistory =
           persistHistory ??
           const bool.fromEnvironment(
             'PERSIST_CHAT_HISTORY',
             defaultValue: true,
           ),
       _client = client ?? http.Client(),
       endpoint = endpoint ?? '$apiBaseUrl/history';

  final bool _persistHistory;
  final http.Client _client;
  final String endpoint;
  final String? authToken;

  Future<List<ChatConversation>> load(String email) async {
    if (!_persistHistory) return [];
    if (_usesRemoteStorage) {
      final response = await _client.get(
        Uri.parse(endpoint),
        headers: _headers,
      );
      if (response.statusCode != 200) {
        throw StateError('Could not load chat history.');
      }
      final payload = jsonDecode(response.body) as Map<String, dynamic>;
      final records = payload['conversations'];
      if (records is! List) return [];
      return records
          .whereType<Map>()
          .map(
            (record) =>
                ChatConversation.fromJson(Map<String, dynamic>.from(record)),
          )
          .where((conversation) => conversation.messages.isNotEmpty)
          .toList();
    }
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
    if (!_persistHistory) return;
    if (_usesRemoteStorage) {
      final response = await _client.post(
        Uri.parse(endpoint),
        headers: {..._headers, 'Content-Type': 'application/json'},
        body: jsonEncode({
          'conversations': conversations
              .map((conversation) => conversation.toJson())
              .toList(),
        }),
      );
      if (response.statusCode != 200) {
        throw StateError('Could not save chat history.');
      }
      return;
    }
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(
      _keyFor(email),
      jsonEncode(
        conversations.map((conversation) => conversation.toJson()).toList(),
      ),
    );
  }

  Future<void> delete(String email, String conversationId) async {
    if (!_persistHistory) return;
    if (_usesRemoteStorage) {
      final response = await _client.delete(
        Uri.parse('$endpoint/${Uri.encodeComponent(conversationId)}'),
        headers: _headers,
      );
      if (response.statusCode != 200) {
        throw StateError('Could not delete chat history.');
      }
      return;
    }
    final conversations = await load(email);
    conversations.removeWhere(
      (conversation) => conversation.id == conversationId,
    );
    await save(email, conversations);
  }

  Future<void> clear(String email) async {
    if (!_persistHistory) return;
    if (_usesRemoteStorage) {
      final response = await _client.delete(
        Uri.parse(endpoint),
        headers: _headers,
      );
      if (response.statusCode != 200) {
        throw StateError('Could not clear chat history.');
      }
      return;
    }
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_keyFor(email));
  }

  bool get _usesRemoteStorage => authToken != null && authToken!.isNotEmpty;

  Map<String, String> get _headers => {'Authorization': 'Bearer ${authToken!}'};

  String _keyFor(String email) =>
      'chat.history.${base64Url.encode(utf8.encode(email.toLowerCase()))}';
}
