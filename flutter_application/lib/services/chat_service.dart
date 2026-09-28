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
          facts: _readFacts(payload['triples']),
        );
      }

      return _errorMessage(
        'RAG.py returned HTTP ${response.statusCode}: ${_readError(response.body)}',
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

  // Turns retrieved triples into short readable facts, e.g.
  // "Garo people - SPEAKS - Garo language".
  List<String> _readFacts(dynamic value) {
    if (value is! List) return const [];
    final facts = <String>[];
    for (final item in value) {
      if (item is! Map) continue;
      final subject = _tidy(item['subject']);
      final predicate = _tidy(item['predicate']).toLowerCase();
      final object = _tidy(item['object']);
      if (subject.isEmpty || object.isEmpty) continue;
      facts.add('$subject \u2192 $predicate \u2192 $object');
    }
    return facts;
  }

  // Makes graph identifiers such as GaroCommunity or HAS_GENDER readable.
  String _tidy(dynamic value) {
    return (value ?? '')
        .toString()
        .replaceAll('_', ' ')
        .replaceAllMapped(
          RegExp(r'([a-z])([A-Z])'),
          (m) => '${m[1]} ${m[2]}',
        )
        .trim();
  }

  // Pulls the backend's error message out of a failed response.
  String _readError(String body) {
    try {
      final payload = jsonDecode(body);
      if (payload is Map && payload['error'] != null) {
        return payload['error'].toString();
      }
    } catch (_) {}
    return 'Check the backend terminal.';
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
