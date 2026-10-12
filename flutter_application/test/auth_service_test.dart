import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:flutter_application/services/auth_service.dart';

import 'test_auth_client.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  AuthService service() => AuthService(client: TestAuthClient());

  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('a registered user can sign in and is not an administrator', () async {
    final session = await service().signIn(
      email: testUser,
      password: testUserPassword,
      rememberMe: false,
    );

    expect(session.email, testUser);
    expect(session.role, UserRole.user);
    expect(session.isAdmin, isFalse);
  });

  test('the existing admin account retains administrator access', () async {
    final session = await service().signIn(
      email: testAdmin,
      password: testAdminPassword,
      rememberMe: false,
    );

    expect(session.email, testAdmin);
    expect(session.role, UserRole.admin);
    expect(session.isAdmin, isTrue);
  });

  test('invalid credentials are rejected', () async {
    expect(
      () => service().signIn(
        email: testUser,
        password: 'wrong-password',
        rememberMe: false,
      ),
      throwsA(isA<Exception>()),
    );
  });

  test('a remembered session restores its token and role', () async {
    await service().signIn(
      email: testAdmin,
      password: testAdminPassword,
      rememberMe: true,
    );

    final restored = await service().restoreSession();

    expect(restored, isNotNull);
    expect(restored!.email, testAdmin);
    expect(restored.role, UserRole.admin);
    expect(restored.token, isNotEmpty);
  });

  test('signing out clears the remembered session', () async {
    final auth = service();
    await auth.signIn(
      email: testUser,
      password: testUserPassword,
      rememberMe: true,
    );

    await auth.signOut();

    expect(await auth.restoreSession(), isNull);
  });
}
