// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:flutter_application/app/app.dart';
import 'package:flutter_application/features/chat/chat_page.dart';
import 'package:flutter_application/features/auth/login_page.dart';
import 'package:flutter_application/services/auth_service.dart';
import 'package:flutter_application/services/chat_service.dart';

class _FakeRagClient extends http.BaseClient {
  // Returns the same response shape as the RAG.py HTTP bridge.
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

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('demo admin credentials are the only valid login', () async {
    final service = AuthService();

    final validSession = await service.signIn(
      email: 'admin',
      password: 'admin123',
      rememberMe: false,
    );
    expect(validSession.email, 'admin');

    expect(
      () => service.signIn(
        email: 'user@example.com',
        password: 'wrongpass',
        rememberMe: false,
      ),
      throwsA(isA<Exception>()),
    );
  });

  testWidgets('renders the login screen', (WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: LoginPage(onSignIn: (email, password, rememberMe) async {}),
      ),
    );
    await tester.pump();

    expect(find.text('Welcome back'), findsOneWidget);
    expect(find.text('Username / Email'), findsOneWidget);
    expect(find.text('Password'), findsOneWidget);
    expect(find.text('Sign in'), findsOneWidget);
    expect(find.byType(TextFormField), findsNWidgets(2));
  });

  testWidgets('switches login UI to Hindi', (WidgetTester tester) async {
    await tester.pumpWidget(const KnowledgeGraphApp());
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Language'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('हिन्दी').last);
    await tester.pumpAndSettle();

    expect(find.text('वापसी पर स्वागत है'), findsOneWidget);
    expect(find.text('उपयोगकर्ता नाम / ईमेल'), findsOneWidget);
    expect(find.text('साइन इन'), findsOneWidget);
    final preferences = await SharedPreferences.getInstance();
    expect(preferences.getString('app.language'), 'hi');

    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpWidget(const KnowledgeGraphApp());
    await tester.pumpAndSettle();
    expect(find.text('वापसी पर स्वागत है'), findsOneWidget);
  });

  testWidgets('sends a question and renders the response', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: ChatPage(service: ChatService(client: _FakeRagClient())),
      ),
    );
    await tester.enterText(
      find.byType(TextField),
      'What entities were extracted?',
    );
    await tester.tap(find.byTooltip('Send question'));
    await tester.pumpAndSettle();

    expect(find.text('What entities were extracted?'), findsOneWidget);
    expect(find.textContaining('Garo people'), findsOneWidget);
  });
}
