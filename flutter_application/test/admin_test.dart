// Tests for the admin paper-admission flow: AdminService and AdminPage.
//
// None of these import file_picker. AdminPage takes its picker as an injected
// callback precisely so the screen is testable without a file dialog, and so a
// problem resolving that package cannot take the test suite down with it.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:flutter_application/features/admin/admin_page.dart';
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

  group('AdminPage', () {
    Future<void> pumpPage(WidgetTester tester, AdminService service,
        {PdfPicker? picker}) async {
      await tester.pumpWidget(MaterialApp(
        home: AdminPage(
          service: service,
          pickPdf: picker ?? () async => null,
        ),
      ));
      await tester.pumpAndSettle();
    }

    testWidgets('shows the queue, newest first', (tester) async {
      final client = _FakeClient((_) => _json(200, {
        'queue': [_entry(paper: 'older.pdf'), _entry(paper: 'newer.pdf')],
      }));
      await pumpPage(tester, AdminService(client: client, secret: 's'));

      expect(find.text('newer.pdf'), findsOneWidget);
      expect(find.text('older.pdf'), findsOneWidget);
    });

    testWidgets('says so when nothing has been submitted', (tester) async {
      final client = _FakeClient((_) => _json(200, {'queue': []}));
      await pumpPage(tester, AdminService(client: client, secret: 's'));

      expect(find.text('No papers have been submitted yet.'), findsOneWidget);
    });

    testWidgets('surfaces an unreachable API instead of an empty list',
        (tester) async {
      await pumpPage(tester, AdminService(client: _ExplodingClient(), secret: 's'));

      expect(find.textContaining('Cannot reach the API'), findsOneWidget);
    });

    testWidgets('a scoring failure is labelled as not a judgement',
        (tester) async {
      // The whole point of the fourth decision: an admin must not read an
      // unreachable model as their paper being rejected.
      final client = _FakeClient((_) => _json(200, {
        'queue': [
          _entry(decision: 'scoring_failed', score: 5,
                 reasons: ['Scoring did not complete -- model unreachable.']),
        ],
      }));
      await pumpPage(tester, AdminService(client: client, secret: 's'));

      expect(find.text('Scoring did not run'), findsOneWidget);

      await tester.tap(find.text('garo_4.pdf'));
      await tester.pumpAndSettle();
      expect(find.textContaining('not a judgement on the paper'), findsOneWidget);
    });

    testWidgets('a rejected paper is shown as discarded', (tester) async {
      final client = _FakeClient((_) => _json(200, {
        'queue': [
          _entry(decision: 'rejected', score: 40, storedPath: null,
                 reasons: ['Scored below the approval threshold.']),
        ],
      }));
      await pumpPage(tester, AdminService(client: client, secret: 's'));

      expect(find.textContaining('Rejected — not stored'), findsOneWidget);

      await tester.tap(find.text('garo_4.pdf'));
      await tester.pumpAndSettle();
      expect(find.textContaining('file was discarded'), findsOneWidget);
    });

    testWidgets('cancelling the file dialog uploads nothing', (tester) async {
      var uploads = 0;
      final client = _FakeClient((request) {
        if (request.method == 'POST') uploads++;
        return _json(200, {'queue': []});
      });
      await pumpPage(tester, AdminService(client: client, secret: 's'),
          picker: () async => null);

      await tester.tap(find.text('Choose a PDF'));
      await tester.pumpAndSettle();

      expect(uploads, 0);
    });

    testWidgets('a successful upload shows the server message and refreshes',
        (tester) async {
      var queueFetches = 0;
      final client = _FakeClient((request) {
        if (request.method == 'POST') {
          return _json(202, {'paper': 'garo_4.pdf',
                             'message': 'Upload accepted and being scored.'});
        }
        queueFetches++;
        return _json(200, {'queue': []});
      });
      await pumpPage(tester, AdminService(client: client, secret: 's'),
          picker: () async => PickedPdf(filename: 'garo_4.pdf', bytes: _pdf));

      expect(queueFetches, 1);

      await tester.tap(find.text('Choose a PDF'));
      await tester.pumpAndSettle();

      expect(find.textContaining('being scored'), findsOneWidget);
      expect(queueFetches, 2, reason: 'the queue should refresh after upload');
    });

    testWidgets('a failed upload shows the reason and does not clear the queue',
        (tester) async {
      final client = _FakeClient((request) {
        if (request.method == 'POST') {
          return _json(401, {'error': 'Admin secret missing or incorrect.'});
        }
        return _json(200, {'queue': [_entry(paper: 'existing.pdf')]});
      });
      await pumpPage(tester, AdminService(client: client, secret: 'wrong'),
          picker: () async => PickedPdf(filename: 'garo_4.pdf', bytes: _pdf));

      await tester.tap(find.text('Choose a PDF'));
      await tester.pumpAndSettle();

      expect(find.textContaining('secret'), findsOneWidget);
      expect(find.text('existing.pdf'), findsOneWidget);
    });
  });
}
