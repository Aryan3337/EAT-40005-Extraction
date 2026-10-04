// Tests for AuthService's two mock accounts and their roles.
//
// WHY ROLES EXIST: the admin upload screen runs a confidence check that costs
// real inference time, and it writes papers into the extraction queue. It must
// not be reachable from the ordinary demo account.
//
// WHAT THIS IS NOT: real authentication. Both credential pairs are literals in
// the Dart source, compared in the browser, and the session is an unsigned
// string in SharedPreferences. Anyone reading the published JavaScript can see
// them, and a viewer can promote themselves to admin by editing local storage.
// The server-side ADMIN_UPLOAD_SECRET is what actually protects the upload
// endpoint; this role only decides which buttons render. See
// KNOWN_LIMITATIONS.md #8.

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:flutter_application/services/auth_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  group('signing in', () {
    test('the demo account signs in as an ordinary user', () async {
      final session = await AuthService().signIn(
        email: AuthService.demoUsername,
        password: AuthService.demoPassword,
        rememberMe: false,
      );

      expect(session.email, AuthService.demoUsername);
      expect(session.role, UserRole.user);
      expect(session.isAdmin, isFalse);
    });

    test('the admin account signs in as an admin', () async {
      final session = await AuthService().signIn(
        email: AuthService.adminUsername,
        password: AuthService.adminPassword,
        rememberMe: false,
      );

      expect(session.email, AuthService.adminUsername);
      expect(session.role, UserRole.admin);
      expect(session.isAdmin, isTrue);
    });

    test('the username is matched case-insensitively', () async {
      final session = await AuthService().signIn(
        email: '  MandiAdmin  ',
        password: AuthService.adminPassword,
        rememberMe: false,
      );

      expect(session.role, UserRole.admin);
    });

    test('an unknown username is rejected', () async {
      expect(
        () => AuthService().signIn(
          email: 'someone@example.com',
          password: AuthService.adminPassword,
          rememberMe: false,
        ),
        throwsA(isA<Exception>()),
      );
    });

    test("the admin password does not unlock the user account", () async {
      // Each account has its own password; they are not interchangeable.
      expect(
        () => AuthService().signIn(
          email: AuthService.demoUsername,
          password: AuthService.adminPassword,
          rememberMe: false,
        ),
        throwsA(isA<Exception>()),
      );
    });

    test("the user password does not unlock the admin account", () async {
      // The one that matters: it must not be possible to reach admin with the
      // credentials the demo account uses.
      expect(
        () => AuthService().signIn(
          email: AuthService.adminUsername,
          password: AuthService.demoPassword,
          rememberMe: false,
        ),
        throwsA(isA<Exception>()),
      );
    });

    test('an empty password is rejected', () async {
      expect(
        () => AuthService().signIn(
          email: AuthService.adminUsername,
          password: '',
          rememberMe: false,
        ),
        throwsA(isA<Exception>()),
      );
    });
  });

  group('restoring a session', () {
    test('a remembered admin comes back as an admin', () async {
      // Without persisting the role, a remembered admin would return on the
      // next launch as an ordinary user and lose the upload screen.
      await AuthService().signIn(
        email: AuthService.adminUsername,
        password: AuthService.adminPassword,
        rememberMe: true,
      );

      final restored = await AuthService().restoreSession();

      expect(restored, isNotNull);
      expect(restored!.email, AuthService.adminUsername);
      expect(restored.role, UserRole.admin);
    });

    test('a remembered user comes back as a user', () async {
      await AuthService().signIn(
        email: AuthService.demoUsername,
        password: AuthService.demoPassword,
        rememberMe: true,
      );

      final restored = await AuthService().restoreSession();

      expect(restored!.role, UserRole.user);
    });

    test('nothing is restored when remember-me was not ticked', () async {
      await AuthService().signIn(
        email: AuthService.adminUsername,
        password: AuthService.adminPassword,
        rememberMe: false,
      );

      expect(await AuthService().restoreSession(), isNull);
    });

    test('signing out clears the stored role as well as the email', () async {
      // A leftover role key would otherwise promote the next person to sign in
      // without remember-me.
      final service = AuthService();
      await service.signIn(
        email: AuthService.adminUsername,
        password: AuthService.adminPassword,
        rememberMe: true,
      );

      await service.signOut();

      expect(await service.restoreSession(), isNull);
      final preferences = await SharedPreferences.getInstance();
      expect(preferences.getString('auth.saved_role'), isNull);
    });

    test('a stored email with no stored role restores as a user', () async {
      // Sessions saved before roles existed have no role key. They must fall
      // back to the lesser privilege, never to admin.
      SharedPreferences.setMockInitialValues({
        'auth.saved_email': AuthService.adminUsername,
      });

      final restored = await AuthService().restoreSession();

      expect(restored!.role, UserRole.user);
    });

    test('an unrecognised stored role restores as a user', () async {
      SharedPreferences.setMockInitialValues({
        'auth.saved_email': AuthService.adminUsername,
        'auth.saved_role': 'superuser',
      });

      final restored = await AuthService().restoreSession();

      expect(restored!.role, UserRole.user);
    });
  });
}
