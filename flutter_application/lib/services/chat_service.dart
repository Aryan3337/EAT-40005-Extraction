import 'dart:convert';

import 'package:http/http.dart' as http;

import '../app/app_localizations.dart';
import '../models/chat_message.dart';
import 'api_config.dart';

class FeedbackRecord {
  const FeedbackRecord({
    this.id = '',
    required this.responseText,
    required this.rating,
    required this.comment,
    required this.createdAt,
    this.status = 'pending',
    this.reviewAction = '',
    this.reviewNote = '',
  });

  final String id;
  final String status;
  final String reviewAction;
  final String reviewNote;
  final String responseText;
  final MessageFeedback rating;
  final String comment;
  final String createdAt;

  factory FeedbackRecord.fromJson(Map<String, dynamic> json) {
    return FeedbackRecord(
      id: json['id']?.toString() ?? '',
      status: json['status']?.toString() ?? 'pending',
      reviewAction: json['review_action']?.toString() ?? '',
      reviewNote: json['review_note']?.toString() ?? '',
      responseText: json['response_text'] as String? ?? '',
      rating: json['rating'] == MessageFeedback.notHelpful.name
          ? MessageFeedback.notHelpful
          : MessageFeedback.helpful,
      comment: json['comment'] as String? ?? '',
      createdAt: json['created_at'] as String? ?? '',
    );
  }
}

// Sends natural-language questions to the RAG.py API.
class ChatService {
  ChatService({
    http.Client? client,
    String? endpoint,
    this.authToken,
    this.strings,
  }) : endpoint = endpoint ?? '$apiBaseUrl/query',
       _client = client ?? http.Client();

  final http.Client _client;
  final String endpoint;
  final String? authToken;
  final AppLocalizations Function()? strings;

  AppLocalizations? get _currentStrings => strings?.call();

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
  Future<ChatMessage> ask(String question, {String language = 'en'}) async {
    try {
      final response = await _client.post(
        Uri.parse(endpoint),
        headers: {
          'Content-Type': 'application/json',
          if (authToken != null) 'Authorization': _bearerToken,
        },
        body: jsonEncode({'query': question, 'language': language}),
      );

      if (response.statusCode >= 200 && response.statusCode < 300) {
        final payload = jsonDecode(response.body) as Map<String, dynamic>;
        final translations = <String, String>{};
        final rawTranslations = payload['translations'];
        if (rawTranslations is Map) {
          for (final entry in rawTranslations.entries) {
            if (entry.key is String && entry.value is String) {
              translations[entry.key as String] = entry.value as String;
            }
          }
        }
        final answer = payload['answer'] as String? ?? _text('noAnswer');
        translations.putIfAbsent(language, () => answer);

        return ChatMessage(
          text: answer,
          author: MessageAuthor.assistant,
          sources: _readSources(payload['triples']),
          translations: translations,
        );
      }

      final strings = _currentStrings;
      return _errorMessage(
        _text('ragHttpError', {
          'status': '${response.statusCode}',
        }).replaceAll('{error}', _readError(response.body, strings)),
      );
    } catch (_) {
      return _errorMessage(_text('cannotReachRag', {'endpoint': endpoint}));
    }
  }

  Future<void> saveFeedback({
    required String conversationId,
    required String responseText,
    required MessageFeedback feedback,
    required String comment,
    List<String> tripleIds = const [],
  }) async {
    if (authToken == null || authToken!.isEmpty) {
      throw StateError('Sign in is required to save feedback.');
    }
    final feedbackEndpoint = endpoint.replaceFirst(
      RegExp(r'/query$'),
      '/feedback',
    );
    final response = await _client.post(
      Uri.parse(feedbackEndpoint),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': _bearerToken,
      },
      body: jsonEncode({
        'conversation_id': conversationId,
        'response_text': responseText,
        'rating': feedback.name,
        'comment': comment.trim(),
        'triple_ids': tripleIds.where((id) => id.isNotEmpty).toList(),
      }),
    );
    if (response.statusCode != 201) {
      throw StateError(_readError(response.body, _currentStrings));
    }
  }

  Future<List<FeedbackRecord>> feedbackHistory() async {
    if (authToken == null || authToken!.isEmpty) {
      throw StateError('Sign in is required to view feedback.');
    }
    final feedbackEndpoint = endpoint.replaceFirst(
      RegExp(r'/query$'),
      '/feedback',
    );
    final response = await _client.get(
      Uri.parse(feedbackEndpoint),
      headers: {'Authorization': _bearerToken},
    );
    if (response.statusCode != 200) {
      throw StateError(_readError(response.body, _currentStrings));
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    final rows = payload['feedback'];
    if (rows is! List) return const [];
    return rows
        .whereType<Map>()
        .map((row) => FeedbackRecord.fromJson(Map<String, dynamic>.from(row)))
        .toList(growable: true);
  }

  // Deletes one of the signed-in user's own feedback entries.
  Future<void> deleteFeedbackItem(String id) async {
    if (authToken == null || authToken!.isEmpty) {
      throw StateError('Sign in is required to delete feedback.');
    }
    final response = await _client.delete(
      Uri.parse(
        '${endpoint.replaceFirst(RegExp(r'/query$'), '/feedback')}/'
        '${Uri.encodeComponent(id)}',
      ),
      headers: {'Authorization': _bearerToken},
    );
    if (response.statusCode != 200) {
      throw StateError(_readError(response.body, _currentStrings));
    }
  }

  Future<void> clearFeedbackHistory() async {
    if (authToken == null || authToken!.isEmpty) {
      throw StateError('Sign in is required to delete feedback.');
    }
    final response = await _client.delete(
      Uri.parse(endpoint.replaceFirst(RegExp(r'/query$'), '/feedback')),
      headers: {'Authorization': _bearerToken},
    );
    if (response.statusCode != 200) {
      throw StateError(_readError(response.body, _currentStrings));
    }
  }

  String get _bearerToken => ['Bearer', authToken!].join(' ');

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
