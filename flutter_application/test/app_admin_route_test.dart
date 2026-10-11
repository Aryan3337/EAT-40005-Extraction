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

Future<void> signIn(WidgetTester tester, String user, String password) async {
  await tester.pumpWidget(const KnowledgeGraphApp());
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

  testWidgets('an admin sees the paper-admission entry point', (tester) async {
    await signIn(tester, AuthService.adminUsername, AuthService.adminPassword);

    expect(find.byTooltip('Paper admission'), findsOneWidget);
  });

  testWidgets('an ordinary user does not', (tester) async {
    await signIn(tester, AuthService.demoUsername, AuthService.demoPassword);

    expect(find.byTooltip('Paper admission'), findsNothing);
  });

  testWidgets('tapping it asks for the admin secret without crashing',
      (tester) async {
    // This is the one that failed in the browser: showDialog needs a context
    // below MaterialApp, and app.dart was passing one from above it.
    await signIn(tester, AuthService.adminUsername, AuthService.adminPassword);

    await tester.tap(find.byTooltip('Paper admission'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('Admin secret'), findsOneWidget);
  });

  testWidgets('entering the secret opens the admin screen', (tester) async {
    await signIn(tester, AuthService.adminUsername, AuthService.adminPassword);
    await tester.tap(find.byTooltip('Paper admission'));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField).last, 'test-secret-123');
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('Paper admission'), findsWidgets);
  });

  testWidgets('cancelling the secret prompt stays on the chat', (tester) async {
    await signIn(tester, AuthService.adminUsername, AuthService.adminPassword);
    await tester.tap(find.byTooltip('Paper admission'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    expect(find.text('Admin secret'), findsNothing);
    expect(find.byTooltip('Paper admission'), findsOneWidget);
  });
}
