import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:flutter_application/app/app_localizations.dart';
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

  // SCRUM-366: switching to a language with no saved translation shows a
  // notice instead of silently showing the answer in another language.
  testWidgets('a missing translation is announced', (
    WidgetTester tester,
  ) async {
    final service = ChatService(client: _FakeRagClient());
    final key = GlobalKey();
    await tester.pumpWidget(
      MaterialApp(home: ChatPage(key: key, service: service)),
    );
    await tester.enterText(find.byType(TextField), 'Where do they live?');
    await tester.tap(find.byTooltip('Send question'));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('translation-missing-notice')),
      findsNothing,
    );

    // The fake answer only has English; switch the app to Bangla.
    await tester.pumpWidget(
      MaterialApp(
        home: ChatPage(
          key: key,
          service: service,
          strings: const AppLocalizations('bn'),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.byKey(const ValueKey('translation-missing-notice')),
      findsOneWidget,
    );
    expect(find.textContaining('English'), findsWidgets);
  });
}
