import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  // SCRUM-372: answers are selectable and can be copied.
  testWidgets('answers are selectable and copy to the clipboard', (
    WidgetTester tester,
  ) async {
    String? copied;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData') {
          copied = (call.arguments as Map)['text'] as String?;
        }
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        null,
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: ChatPage(service: ChatService(client: _FakeRagClient())),
      ),
    );
    await tester.enterText(find.byType(TextField), 'Where do they live?');
    await tester.tap(find.byTooltip('Send question'));
    await tester.pumpAndSettle();

    expect(
      find.byWidgetPredicate(
        (widget) =>
            widget is SelectableText &&
            (widget.data ?? '').contains('Garo people'),
      ),
      findsOneWidget,
    );

    await tester.tap(find.byTooltip('Copy answer'));
    await tester.pump();
    expect(copied, contains('Garo people'));
    expect(find.text('Answer copied'), findsOneWidget);
  });
}
