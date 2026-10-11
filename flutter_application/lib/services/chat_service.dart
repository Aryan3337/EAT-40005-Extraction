import 'dart:convert';

import 'package:http/http.dart' as http;

import '../app/app_localizations.dart';
import '../models/chat_message.dart';
import 'api_config.dart';

// Sends natural-language questions to the RAG.py API.
class ChatService {
  ChatService({
    http.Client? client,
    String? endpoint,
    AppLocalizations Function()? strings,
  }) : endpoint = endpoint ?? '$apiBaseUrl/query',
       _client = client ?? http.Client(),
       _strings = strings;

  final http.Client _client;
  final String endpoint;
  final AppLocalizations Function()? _strings;

  AppLocalizations? get _currentStrings => _strings?.call();

  String _text(String key, [Map<String, String>? replacements]) {
    final strings = _currentStrings;
    if (strings == null) return key;

    var text = strings.text(key);
    if (replacements != null) {
      replacements.forEach((placeholder, value) {
        text = text.replaceAll('{$placeholder}', value);
      });
    }
    return text;
  }

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
          text: payload['answer'] as String? ?? _text('noAnswer'),
          author: MessageAuthor.assistant,
          sources: _readSources(payload['triples']),
        );
      }

      final strings = _currentStrings;
      return _errorMessage(
        _text('ragHttpError', {'status': '${response.statusCode}'})
            .replaceAll('{error}', _readError(response.body, strings)),
      );
    } catch (_) {
      return _errorMessage(
        _text('cannotReachRag', {'endpoint': endpoint}),
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
  String _readError(String body, AppLocalizations? strings) {
    try {
      final payload = jsonDecode(body);
      if (payload is Map && payload['error'] != null) {
        return payload['error'].toString();
      }
    } catch (_) {}
    return strings?.text('checkBackend') ?? 'Check backend';
  }

  // Explains why a live graph answer could not be displayed.
  ChatMessage _errorMessage(String text) {
    return ChatMessage(author: MessageAuthor.assistant, text: text);
  }
}
