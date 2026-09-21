import 'package:shared_preferences/shared_preferences.dart';

class AuthSession {
  const AuthSession({required this.email});

  final String email;
}

class AuthService {
  static const _savedEmailKey = 'auth.saved_email';

  Future<AuthSession?> restoreSession() async {
    final preferences = await SharedPreferences.getInstance();
    final email = preferences.getString(_savedEmailKey);
    return email == null ? null : AuthSession(email: email);
  }

  Future<AuthSession> signIn({
    required String email,
    required String password,
    required bool rememberMe,
  }) async {
    if (rememberMe) {
      final preferences = await SharedPreferences.getInstance();
      await preferences.setString(_savedEmailKey, email);
    } else {
      await signOut();
    }
    return AuthSession(email: email);
  }

  Future<void> signOut() async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_savedEmailKey);
  }
}
