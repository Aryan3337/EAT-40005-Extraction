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

import 'package:flutter_application/features/chat/chat_page.dart';
import 'package:flutter_application/main.dart';
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
  testWidgets('renders the knowledge graph assistant', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const KnowledgeGraphApp());

    expect(find.text('Mandi/Garo ChatBot'), findsOneWidget);
    expect(find.text('Ask me anything'), findsNWidgets(2));
    expect(find.byType(TextField), findsOneWidget);
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
