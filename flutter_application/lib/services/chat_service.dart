import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../models/chat_message.dart';

// Sends natural-language questions to the RAG.py API.
class ChatService {
  ChatService({http.Client? client, String? endpoint})
    : endpoint = endpoint ?? _defaultEndpoint,
      _client = client ?? http.Client();

  final http.Client _client;
  final String endpoint;

  // Selects the host address that reaches the computer running RAG.py.
  static String get _defaultEndpoint {
    if (defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000/query';
    }
    return 'http://127.0.0.1:8000/query';
  }

  // Queries RAG.py and maps its response into a displayable chat message.
  Future<ChatMessage> ask(String question) async {
    try {
      final response = await _client.post(
        Uri.parse(endpoint),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'query': question}),
      );

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final payload = jsonDecode(response.body) as Map<String, dynamic>;
        return ChatMessage(
          text: payload['answer'] as String? ?? 'The graph returned no answer.',
          author: MessageAuthor.assistant,
          sources: _readSources(payload['sources']),
        );
      }

      return _errorMessage(
        'RAG.py returned HTTP ${response.statusCode}. Check the backend terminal.',
      );
    } catch (_) {
      return _errorMessage(
        'Cannot reach RAG.py at $endpoint. Start the RAG API and try again.',
      );
    }
  }

  // Normalizes optional source records from the API response.
  List<String> _readSources(dynamic value) {
    if (value is! List) return const [];
    return value.map((source) => source.toString()).toList();
  }

  // Explains why a live graph answer could not be displayed.
  ChatMessage _errorMessage(String text) {
    return ChatMessage(
      author: MessageAuthor.assistant,
      text: text,
      sources: const ['RAG.py connection'],
    );
  }
}
