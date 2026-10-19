import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:flutter_application/features/chat/chat_page.dart';
import 'package:flutter_application/services/chat_service.dart';

class _FakeRagClient extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final body = jsonEncode({
      'answer': '(Garo people) -[LIVE_IN]-> (Meghalaya)',
      'sources': ['Page 4'],
    });
    return http.StreamedResponse(
      Stream.value(utf8.encode(body)),
      200,
      headers: {'content-type': 'application/json'},
    );
  }
}

// Holds the answer back until the test releases it, so the "bot is
// thinking" state can be inspected.
class _SlowRagClient extends http.BaseClient {
  final release = Completer<void>();

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    await release.future;
    return _FakeRagClient().send(request);
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  // SCRUM-371: the send button is disabled while the bot is thinking.
  testWidgets('send is disabled until the answer arrives', (
    WidgetTester tester,
  ) async {
    final client = _SlowRagClient();
    await tester.pumpWidget(
      MaterialApp(home: ChatPage(service: ChatService(client: client))),
    );
    await tester.enterText(find.byType(TextField), 'First question');
    await tester.tap(find.byTooltip('Send question'));
    await tester.pump();

    final waiting = find.byTooltip('Waiting for the answer…');
    expect(waiting, findsOneWidget);
    final button = tester.widget<IconButton>(
      find.ancestor(of: waiting, matching: find.byType(IconButton)),
    );
    expect(button.onPressed, isNull);

    // Pressing Enter while waiting does not send a second question.
    await tester.enterText(find.byType(TextField), 'Second question');
    await tester.testTextInput.receiveAction(TextInputAction.send);
    await tester.pump();
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.controller!.text, 'Second question'); // not sent yet

    client.release.complete();
    await tester.pumpAndSettle();
    expect(find.byTooltip('Send question'), findsOneWidget);
    expect(find.textContaining('Garo people'), findsOneWidget);
  });
}
