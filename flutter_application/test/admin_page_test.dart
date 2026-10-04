// Tests for the AdminPage screen: the verdict categories, drilling into one,
// the extraction placeholder, and live updates.
//
// None of these import file_picker. AdminPage takes its picker as an injected
// callback so the screen is testable without a file dialog.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:flutter_application/features/admin/admin_page.dart';
import 'package:flutter_application/services/admin_service.dart';

class _FakeClient extends http.BaseClient {
  _FakeClient(this.respond);

  final http.Response Function(http.BaseRequest request) respond;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
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
  'at': '2026-10-05T09:00:00+00:00',
};

void main() {
  // pollInterval is null in most of these on purpose: a periodic timer never
  // lets pumpAndSettle settle. The live-update group opts in and drives the
  // clock with pump() instead.
  Future<void> pumpPage(WidgetTester tester, AdminService service,
      {PdfPicker? picker, Duration? pollInterval, PdfViewer? viewer}) async {
    await tester.pumpWidget(MaterialApp(
      home: AdminPage(
        service: service,
        pickPdf: picker ?? () async => null,
        viewPdf: viewer,
        pollInterval: pollInterval,
      ),
    ));
    await tester.pumpAndSettle();
  }

  Future<void> openCategory(WidgetTester tester, String label) async {
    await tester.tap(find.text(label));
    await tester.pumpAndSettle();
  }

  _FakeClient queueOf(List<Map<String, dynamic>> entries) =>
      _FakeClient((_) => _json(200, {'queue': entries}));

  group('the verdict categories', () {
    testWidgets('the top level is the verdicts, not a list of papers',
        (tester) async {
      // Previously every admission was listed flat. An admin wants to know
      // how many are waiting on them, not to scroll a history.
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'a.pdf'),
        _entry(paper: 'b.pdf', decision: 'rejected', storedPath: null),
      ]), secret: 's'));

      expect(find.text('Approved'), findsOneWidget);
      expect(find.text('Manual review'), findsOneWidget);
      expect(find.text('Rejected'), findsOneWidget);
      expect(find.text('a.pdf'), findsNothing);
      expect(find.text('b.pdf'), findsNothing);
    });

    testWidgets('each category counts the papers in it', (tester) async {
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'a.pdf'),
        _entry(paper: 'b.pdf'),
        _entry(paper: 'c.pdf', decision: 'rejected', storedPath: null),
      ]), secret: 's'));

      expect(find.text('2'), findsOneWidget);
      expect(find.text('1'), findsWidgets);
    });

    testWidgets('a scoring failure is kept apart from the verdicts',
        (tester) async {
      // Folding it into Rejected would tell an admin their paper failed on
      // merit when the confidence model was simply unreachable.
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(decision: 'scoring_failed', score: 5),
      ]), secret: 's'));

      expect(find.text('Rejected'), findsOneWidget);
      expect(find.textContaining("Scoring didn't run"), findsOneWidget);
    });
  });

  group('drilling into a category', () {
    testWidgets('it lists only that category\'s papers', (tester) async {
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'approved.pdf'),
        _entry(paper: 'denied.pdf', decision: 'rejected', storedPath: null),
      ]), secret: 's'));

      await openCategory(tester, 'Approved');

      expect(find.text('approved.pdf'), findsOneWidget);
      expect(find.text('denied.pdf'), findsNothing);
    });

    testWidgets('a rejected paper shows why it was turned down',
        (tester) async {
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'denied.pdf', decision: 'rejected', storedPath: null,
               reasons: ['Scored below the approval threshold.']),
      ]), secret: 's'));

      await openCategory(tester, 'Rejected');

      expect(find.textContaining('below the approval threshold'), findsOneWidget);
    });

    testWidgets('going back returns to the categories', (tester) async {
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'approved.pdf'),
      ]), secret: 's'));
      await openCategory(tester, 'Approved');
      expect(find.text('approved.pdf'), findsOneWidget);

      await tester.tap(find.byTooltip('Back to categories'));
      await tester.pumpAndSettle();

      expect(find.text('Manual review'), findsOneWidget);
      expect(find.text('approved.pdf'), findsNothing);
    });

    testWidgets('an empty category says so rather than looking broken',
        (tester) async {
      await pumpPage(tester, AdminService(client: queueOf([]), secret: 's'));

      await openCategory(tester, 'Approved');

      expect(find.textContaining('No papers'), findsOneWidget);
    });
  });

  group('the extraction placeholder', () {
    testWidgets('only an approved paper offers extraction', (tester) async {
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'approved.pdf'),
      ]), secret: 's'));

      await openCategory(tester, 'Approved');

      expect(find.widgetWithText(FilledButton, 'Extract'), findsOneWidget);
    });

    testWidgets('a manual-review paper does not', (tester) async {
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'maybe.pdf', decision: 'held_for_review'),
      ]), secret: 's'));

      await openCategory(tester, 'Manual review');

      expect(find.text('maybe.pdf'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Extract'), findsNothing);
    });

    testWidgets('a rejected paper does not', (tester) async {
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'denied.pdf', decision: 'rejected', storedPath: null),
      ]), secret: 's'));

      await openCategory(tester, 'Rejected');

      expect(find.widgetWithText(FilledButton, 'Extract'), findsNothing);
    });

    testWidgets('it says plainly that it is not wired up', (tester) async {
      // A button that looks real but silently does nothing is worse than no
      // button: an admin would believe extraction had started.
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'approved.pdf'),
      ]), secret: 's'));
      await openCategory(tester, 'Approved');

      await tester.tap(find.widgetWithText(FilledButton, 'Extract'));
      await tester.pumpAndSettle();

      expect(find.textContaining('not wired up'), findsOneWidget);
    });
  });

  group('live updates', () {
    testWidgets('a verdict appears without the admin refreshing',
        (tester) async {
      // Why this exists: scoring takes minutes, and the admin previously had
      // to reload the page to discover what had happened.
      var polls = 0;
      final client = _FakeClient((_) {
        polls++;
        return _json(200, {'queue': polls > 1 ? [_entry(paper: 'late.pdf')] : []});
      });

      await tester.pumpWidget(MaterialApp(
        home: AdminPage(
          service: AdminService(client: client, secret: 's'),
          pickPdf: () async => null,
          pollInterval: const Duration(seconds: 2),
        ),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.text('1'), findsNothing, reason: 'nothing approved yet');

      await tester.pump(const Duration(seconds: 3));
      await tester.pump(const Duration(milliseconds: 50));

      expect(polls, greaterThan(1));
      expect(find.text('1'), findsWidgets, reason: 'the approved count arrived');

      await tester.pumpWidget(const SizedBox.shrink());
    });

    testWidgets('polling stops when the page goes away', (tester) async {
      var polls = 0;
      final client = _FakeClient((_) {
        polls++;
        return _json(200, {'queue': []});
      });

      await tester.pumpWidget(MaterialApp(
        home: AdminPage(
          service: AdminService(client: client, secret: 's'),
          pickPdf: () async => null,
          pollInterval: const Duration(seconds: 1),
        ),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 2));
      final before = polls;

      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(seconds: 5));

      expect(polls, before, reason: 'a disposed page must not keep polling');
    });

    testWidgets('an uploaded paper shows as scoring before its verdict lands',
        (tester) async {
      // Between upload and verdict the paper is in no category at all, so
      // without this the admin uploads and sees nothing change for minutes.
      final client = _FakeClient((request) {
        if (request.method == 'POST') {
          return _json(202, {'paper': 'garo_4.pdf', 'message': 'being scored'});
        }
        return _json(200, {'queue': []});
      });

      await pumpPage(tester, AdminService(client: client, secret: 's'),
          picker: () async => PickedPdf(filename: 'garo_4.pdf', bytes: _pdf));

      await tester.tap(find.text('Choose a PDF'));
      // pump, not pumpAndSettle: the pending tile carries a progress spinner
      // that animates forever, so nothing ever settles.
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.textContaining('Scoring'), findsWidgets);
      expect(find.text('garo_4.pdf'), findsOneWidget);

      await tester.pumpWidget(const SizedBox.shrink());
    });
  });

  group('manual review', () {
    testWidgets('a paper under review offers view, approve and reject',
        (tester) async {
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'maybe.pdf', decision: 'held_for_review'),
      ]), secret: 's'), viewer: (name, bytes) async {});

      await openCategory(tester, 'Manual review');

      expect(find.text('View paper'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, 'Approve'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Reject'), findsOneWidget);
    });

    testWidgets('an approved paper offers neither approve nor reject',
        (tester) async {
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'done.pdf'),
      ]), secret: 's'), viewer: (name, bytes) async {});

      await openCategory(tester, 'Approved');

      expect(find.widgetWithText(FilledButton, 'Approve'), findsNothing);
      expect(find.widgetWithText(OutlinedButton, 'Reject'), findsNothing);
    });

    testWidgets('without a viewer the app does not offer to show the paper',
        (tester) async {
      // A build that cannot render a PDF must hide the button rather than
      // present one that silently does nothing.
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'maybe.pdf', decision: 'held_for_review'),
      ]), secret: 's'));

      await openCategory(tester, 'Manual review');

      expect(find.text('View paper'), findsNothing);
    });

    testWidgets('a rejected paper is not offered for viewing', (tester) async {
      // An automatically rejected paper was never stored, so there is nothing
      // on the server to fetch.
      await pumpPage(tester, AdminService(client: queueOf([
        _entry(paper: 'gone.pdf', decision: 'rejected', storedPath: null),
      ]), secret: 's'), viewer: (name, bytes) async {});

      await openCategory(tester, 'Rejected');

      expect(find.text('View paper'), findsNothing);
    });

    testWidgets('viewing fetches the bytes and hands them to the viewer',
        (tester) async {
      Uint8List? shown;
      final client = _FakeClient((request) {
        if (request.url.path == '/admin/paper') {
          return http.Response.bytes(_pdf, 200);
        }
        return _json(200, {'queue': [
          _entry(paper: 'maybe.pdf', decision: 'held_for_review'),
        ]});
      });

      await pumpPage(tester, AdminService(client: client, secret: 's'),
          viewer: (name, bytes) async => shown = bytes);
      await openCategory(tester, 'Manual review');

      await tester.tap(find.text('View paper'));
      await tester.pumpAndSettle();

      expect(shown, _pdf);
    });

    testWidgets('approving asks why, then submits it', (tester) async {
      Map<String, dynamic>? submitted;
      final client = _FakeClient((request) {
        if (request.method == 'POST' && request is http.Request) {
          submitted = jsonDecode(request.body) as Map<String, dynamic>;
          return _json(200, {});
        }
        return _json(200, {'queue': [
          _entry(paper: 'maybe.pdf', decision: 'held_for_review'),
        ]});
      });

      await pumpPage(tester, AdminService(client: client, secret: 's'),
          viewer: (name, bytes) async {});
      await openCategory(tester, 'Manual review');

      await tester.tap(find.widgetWithText(FilledButton, 'Approve'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Approve maybe.pdf'), findsOneWidget);

      await tester.enterText(find.byType(TextField).last, 'Read it, sound.');
      await tester.tap(find.widgetWithText(FilledButton, 'Approve').last);
      await tester.pumpAndSettle();

      expect(submitted?['paper'], 'maybe.pdf');
      expect(submitted?['approve'], isTrue);
      expect(submitted?['note'], 'Read it, sound.');
    });

    testWidgets('rejecting submits approve=false', (tester) async {
      Map<String, dynamic>? submitted;
      final client = _FakeClient((request) {
        if (request.method == 'POST' && request is http.Request) {
          submitted = jsonDecode(request.body) as Map<String, dynamic>;
          return _json(200, {});
        }
        return _json(200, {'queue': [
          _entry(paper: 'maybe.pdf', decision: 'held_for_review'),
        ]});
      });

      await pumpPage(tester, AdminService(client: client, secret: 's'),
          viewer: (name, bytes) async {});
      await openCategory(tester, 'Manual review');

      await tester.tap(find.widgetWithText(OutlinedButton, 'Reject'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Reject').last);
      await tester.pumpAndSettle();

      expect(submitted?['approve'], isFalse);
    });

    testWidgets('cancelling the dialog submits nothing', (tester) async {
      var posts = 0;
      final client = _FakeClient((request) {
        if (request.method == 'POST') posts++;
        return _json(200, {'queue': [
          _entry(paper: 'maybe.pdf', decision: 'held_for_review'),
        ]});
      });

      await pumpPage(tester, AdminService(client: client, secret: 's'),
          viewer: (name, bytes) async {});
      await openCategory(tester, 'Manual review');

      await tester.tap(find.widgetWithText(FilledButton, 'Approve'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(posts, 0);
    });
  });
}
