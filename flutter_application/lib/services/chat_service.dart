import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/chat_message.dart';
import 'api_config.dart';

// Sends natural-language questions to the RAG.py API.
class ChatService {
  ChatService({http.Client? client, String? endpoint})
    : endpoint = endpoint ?? '$apiBaseUrl/query',
      _client = client ?? http.Client();

  final http.Client _client;
  final String endpoint;

  // Queries RAG.py and maps its answer and evidence into a chat message.
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
          sources: _readSources(payload['triples']),
        );
      }

      return _errorMessage(
        'RAG.py returned HTTP ${response.statusCode}: ${_readError(response.body)}',
      );
    } catch (_) {
      return _errorMessage(
        'Cannot reach RAG.py at $endpoint. '
        'Start the RAG API and try again.',
      );
    }
  }

  // Converts knowledge-graph triples into evidence shown beneath the answer.
  List<SourceEvidence> _readSources(dynamic value) {
    if (value is! List) return const [];

    final sources = <SourceEvidence>[];

    for (final item in value) {
      if (item is! Map) continue;

      final source = SourceEvidence.fromJson(Map<String, dynamic>.from(item));

      final hasTriple =
          source.subject.isNotEmpty &&
          source.predicate.isNotEmpty &&
          source.object.isNotEmpty;
      final hasSupportingText = source.supportingText.isNotEmpty;

      if (hasTriple || hasSupportingText) {
        sources.add(source);
      }
    }

    return sources;
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
    return ChatMessage(author: MessageAuthor.assistant, text: text);
  }
}
