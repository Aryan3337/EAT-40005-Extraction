// Covers the seam the other tests missed: app.dart's own admin flow.
//
// admin_test.dart pumps AdminPage directly, so it never exercised signing in
// and tapping through from the chat header. That gap hid a real crash --
// showDialog was called with the context of the widget that BUILDS
// MaterialApp, which has no Navigator above it.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:flutter_application/app/app.dart';
import 'package:flutter_application/services/auth_service.dart';

import 'test_auth_client.dart';

Future<void> signIn(WidgetTester tester, String user, String password) async {
  await tester.pumpWidget(
    KnowledgeGraphApp(authService: AuthService(client: TestAuthClient())),
  );
  await tester.pumpAndSettle();

  final fields = find.byType(TextFormField);
  await tester.enterText(fields.first, user);
  await tester.enterText(fields.last, password);
  await tester.tap(find.text('Sign in'));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('an admin lands on the dashboard, not the chat', (tester) async {
    await signIn(tester, testAdmin, testAdminPassword);

    expect(find.text('Admin dashboard'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
  });

  testWidgets('an ordinary user lands on the chat', (tester) async {
    await signIn(tester, testUser, testUserPassword);

    expect(find.text('Admin dashboard'), findsNothing);
    expect(find.byTooltip('Admin dashboard'), findsNothing);
    expect(find.byType(TextField), findsOneWidget);
  });

  testWidgets('the dashboard lists every feature as a tile', (tester) async {
    await signIn(tester, testAdmin, testAdminPassword);

    expect(tester.takeException(), isNull);
    expect(find.text('Chatbot'), findsOneWidget);
    expect(find.text('Paper admission'), findsOneWidget);
    expect(find.text('Feedback review'), findsOneWidget);
    expect(find.text('Manage users'), findsOneWidget);
  });

  testWidgets('the chatbot tile opens the chat and back returns', (
    tester,
  ) async {
    await signIn(tester, testAdmin, testAdminPassword);

    await tester.tap(find.text('Chatbot'));
    await tester.pumpAndSettle();
    expect(find.byType(TextField), findsOneWidget);
    expect(find.text('Feedback review'), findsNothing);

    await tester.tap(find.byTooltip('Admin dashboard'));
    await tester.pumpAndSettle();
    expect(find.text('Feedback review'), findsOneWidget);
  });

  testWidgets('signing out from the dashboard returns to login', (
    tester,
  ) async {
    await signIn(tester, testAdmin, testAdminPassword);

    await tester.tap(find.byTooltip('Sign out'));
    await tester.pumpAndSettle();

    expect(find.text('Sign in'), findsOneWidget);
  });

  testWidgets('tapping paper admission asks for the admin secret', (
    tester,
  ) async {
    // This is the one that failed in the browser: showDialog needs a context
    // below MaterialApp, and app.dart was passing one from above it.
    await signIn(tester, testAdmin, testAdminPassword);

    await tester.tap(find.text('Paper admission'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('Admin secret'), findsOneWidget);
  });

  testWidgets('entering the secret opens the admin screen', (tester) async {
    await signIn(tester, testAdmin, testAdminPassword);
    await tester.tap(find.text('Paper admission'));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField).last, 'test-secret-123');
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('Admin dashboard'), findsNothing);
    expect(find.text('Paper admission'), findsWidgets);

    await tester.tap(find.byTooltip('Back to dashboard'));
    await tester.pumpAndSettle();
    expect(find.text('Admin dashboard'), findsOneWidget);
  });

  testWidgets('cancelling the secret prompt stays on the dashboard', (
    tester,
  ) async {
    await signIn(tester, testAdmin, testAdminPassword);
    await tester.tap(find.text('Paper admission'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('Admin secret'), findsNothing);
    expect(find.text('Feedback review'), findsOneWidget);
  });
}
