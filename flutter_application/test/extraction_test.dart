// Tests for the extraction states and the button that starts them.
//
// Extraction is ~72 minutes, so the UI can never show a result -- only a
// state it polled. These states arrive on the SAME /admin/queue rows the
// confidence verdicts use, because the server appends them to the same
// append-only queue and later entries win.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:flutter_application/models/ingest_entry.dart';
import 'package:flutter_application/services/admin_service.dart';

class _FakeClient extends http.BaseClient {
  _FakeClient(this.respond);

  final http.Response Function(http.BaseRequest request) respond;
  final List<http.BaseRequest> requests = [];
  final List<List<int>> bodies = [];

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    requests.add(request);
    if (request is http.Request) bodies.add(request.bodyBytes);
    final response = respond(request);
    return http.StreamedResponse(
      Stream.value(utf8.encode(response.body)),
      response.statusCode,
      headers: {'content-type': 'application/json'},
    );
  }
}

http.Response _json(int status, Object body) =>
    http.Response(jsonEncode(body), status);

AdminService _service(http.Client client) => AdminService(
  client: client,
  endpoint: 'http://127.0.0.1:8000',
  secret: 's3cret',
);

void main() {
  group('extraction states on a queue row', () {
    test('a running extraction is its own state, not an approval', () {
      expect(
        IngestEntry.decisionFrom('extracting'),
        IngestDecision.extracting,
      );
    });

    test('a finished extraction carries the triple count', () {
      final entry = IngestEntry.fromJson({
        'paper': 'garo_2.pdf',
        'decision': 'extracted',
        'triples_loaded': 212,
      });

      expect(entry.decision, IngestDecision.extracted);
      expect(entry.triplesLoaded, 212);
    });

    test('zero triples is still an extraction that finished', () {
      // Nothing surviving the three gates is the gates working, and an
      // admin must be able to tell that from a crash.
      final entry = IngestEntry.fromJson({
        'paper': 'thin.pdf',
        'decision': 'extracted',
        'triples_loaded': 0,
      });

      expect(entry.decision, IngestDecision.extracted);
      expect(entry.triplesLoaded, 0);
    });

    test('a failed extraction carries why', () {
      final entry = IngestEntry.fromJson({
        'paper': 'garo_2.pdf',
        'decision': 'extraction_failed',
        'error': 'ConnectionRefusedError: ollama',
      });

      expect(entry.decision, IngestDecision.extractionFailed);
      expect(entry.error, contains('ollama'));
    });
  });

  group('AdminService.startExtraction', () {
    test('posts the paper to /admin/extract with the admin secret', () async {
      final client = _FakeClient(
        (_) => _json(202, {'paper': 'garo_2.pdf', 'status': 'extracting'}),
      );

      await _service(client).startExtraction('garo_2.pdf');

      final request = client.requests.single;
      expect(request.url.path, '/admin/extract');
      expect(request.headers['X-Admin-Secret'], 's3cret');
      expect(utf8.decode(client.bodies.single), contains('garo_2.pdf'));
    });

    test('surfaces the refusal when one is already running', () async {
      // One at a time: two 72-minute runs on one CPU-only Ollama would make
      // both crawl and starve the chatbot. The admin has to be told plainly.
      final client = _FakeClient(
        (_) => _json(409, {'error': 'An extraction is already running.'}),
      );

      expect(
        () => _service(client).startExtraction('garo_2.pdf'),
        throwsA(
          isA<AdminException>().having(
            (e) => e.message,
            'message',
            contains('already running'),
          ),
        ),
      );
    });

    test('surfaces a refusal to extract an unapproved paper', () async {
      final client = _FakeClient(
        (_) => _json(409, {
          'error': "'contested.pdf' is held_for_review, not ready_to_extract.",
        }),
      );

      expect(
        () => _service(client).startExtraction('contested.pdf'),
        throwsA(isA<AdminException>()),
      );
    });
  });
}
