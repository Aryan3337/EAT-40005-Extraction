// Tests for AdminService and IngestEntry -- the HTTP layer and the queue row.
//
// The AdminPage widget tests live in admin_page_test.dart. Neither file
// imports file_picker: AdminPage takes its picker as an injected callback, so
// a problem resolving that package cannot take the suite down with it.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:flutter_application/models/ingest_entry.dart';
import 'package:flutter_application/services/admin_service.dart';

// A client that answers with whatever the test sets up, and records what it
// was asked for.
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

class _ExplodingClient extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    throw Exception('connection refused');
  }
}

http.Response _json(int status, Object body) =>
    http.Response(jsonEncode(body), status);

final _pdf = Uint8List.fromList(utf8.encode('%PDF-1.4 fake'));

Map<String, dynamic> _entry({
  String paper = 'garo_4.pdf',
  String decision = 'ready_to_extract',
  int? score = 80,
  List<String> reasons = const [],
  String? storedPath = 'uploads/papers/garo_4.pdf',
}) => {
  'paper': paper,
  'decision': decision,
  'score': score,
  'max_score': 100,
  'outcome': 'APPROVED',
  'reasons': reasons,
  'stored_path': storedPath,
  'at': '2026-10-04T23:00:00+00:00',
};

void main() {
  group('AdminService.uploadPdf', () {
    test('sends the secret, the filename and the raw bytes', () async {
      final client = _FakeClient(
        (_) => _json(202, {'paper': 'garo_4.pdf', 'message': 'Upload accepted.'}),
      );
      final service = AdminService(
        client: client,
        endpoint: 'http://127.0.0.1:8000',
        secret: 's3cret',
      );

      final ack = await service.uploadPdf(bytes: _pdf, filename: 'garo_4.pdf');

      expect(ack.paper, 'garo_4.pdf');
      final request = client.requests.single;
      expect(request.url.path, '/admin/upload');
      expect(request.headers['X-Admin-Secret'], 's3cret');
      expect(request.headers['X-Filename'], 'garo_4.pdf');
      expect(client.bodies.single, _pdf);
    });

    test('a 202 is an acceptance, not a verdict', () async {
      // Scoring takes minutes and runs server-side; the decision arrives via
      // the queue, so nothing here should imply the paper was approved.
      final client = _FakeClient(
        (_) => _json(202, {'paper': 'garo_4.pdf', 'message': 'being scored'}),
      );
      final ack = await AdminService(client: client, secret: 's')
          .uploadPdf(bytes: _pdf, filename: 'garo_4.pdf');

      expect(ack.message, contains('scored'));
    });

    test('a 401 explains that the secret is wrong', () async {
      final client = _FakeClient((_) => _json(401, {'error': 'Admin secret missing or incorrect.'}));

      expect(
        () => AdminService(client: client, secret: 'nope')
            .uploadPdf(bytes: _pdf, filename: 'garo_4.pdf'),
        throwsA(isA<AdminException>().having(
          (e) => e.message, 'message', contains('secret'))),
      );
    });

    test('a 503 says the server has no secret configured', () async {
      // Distinct from a wrong secret: nothing the admin types will help, the
      // server needs ADMIN_UPLOAD_SECRET setting.
      final client = _FakeClient((_) => _json(503, {}));

      expect(
        () => AdminService(client: client, secret: 's')
            .uploadPdf(bytes: _pdf, filename: 'garo_4.pdf'),
        throwsA(isA<AdminException>().having(
          (e) => e.message, 'message', contains('ADMIN_UPLOAD_SECRET'))),
      );
    });

    test("a 400 surfaces the server's own reason", () async {
      final client = _FakeClient(
        (_) => _json(400, {'error': 'That file is not a PDF.'}),
      );

      expect(
        () => AdminService(client: client, secret: 's')
            .uploadPdf(bytes: _pdf, filename: 'x.pdf'),
        throwsA(isA<AdminException>().having(
          (e) => e.message, 'message', contains('not a PDF'))),
      );
    });

    test('an unreachable API says how to start it', () async {
      expect(
        () => AdminService(client: _ExplodingClient(), secret: 's')
            .uploadPdf(bytes: _pdf, filename: 'garo_4.pdf'),
        throwsA(isA<AdminException>().having(
          (e) => e.message, 'message', contains('rag.py'))),
      );
    });
  });

  group('AdminService.fetchQueue', () {
    test('parses entries and returns the newest first', () async {
      final client = _FakeClient((_) => _json(200, {
        'queue': [
          _entry(paper: 'first.pdf'),
          _entry(paper: 'second.pdf', decision: 'rejected', storedPath: null),
        ],
      }));

      final queue = await AdminService(client: client, secret: 's').fetchQueue();

      expect(queue.map((e) => e.paper), ['second.pdf', 'first.pdf']);
      expect(queue.first.decision, IngestDecision.rejected);
      expect(queue.first.isStored, isFalse);
      expect(queue.last.isStored, isTrue);
    });

    test('an empty queue is not an error', () async {
      final client = _FakeClient((_) => _json(200, {'queue': []}));
      expect(await AdminService(client: client, secret: 's').fetchQueue(), isEmpty);
    });

    test('a malformed body yields an empty queue rather than throwing', () async {
      final client = _FakeClient((_) => http.Response('not json', 200));
      expect(await AdminService(client: client, secret: 's').fetchQueue(), isEmpty);
    });

    test('an unknown decision string does not crash parsing', () async {
      final client = _FakeClient(
        (_) => _json(200, {'queue': [_entry(decision: 'something_new')]}),
      );
      final queue = await AdminService(client: client, secret: 's').fetchQueue();
      expect(queue.single.decision, IngestDecision.unknown);
    });
  });

  group('IngestEntry', () {
    test('a scoring failure is not treated as a verdict', () async {
      final entry = IngestEntry.fromJson(_entry(decision: 'scoring_failed', score: 5));
      expect(entry.isVerdict, isFalse);
    });

    test('every real decision is a verdict', () {
      for (final decision in ['ready_to_extract', 'held_for_review', 'rejected']) {
        expect(IngestEntry.fromJson(_entry(decision: decision)).isVerdict, isTrue,
            reason: decision);
      }
    });

    test('a missing score reads as a dash rather than null', () {
      expect(IngestEntry.fromJson(_entry(score: null)).scoreLabel, '—');
    });
  });
}
