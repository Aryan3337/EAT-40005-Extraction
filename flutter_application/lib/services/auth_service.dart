import 'package:shared_preferences/shared_preferences.dart';

/// What a signed-in person is allowed to see.
///
/// This decides which buttons render, nothing more. The admin upload endpoint
/// is protected server-side by ADMIN_UPLOAD_SECRET, because a role held in the
/// browser is not a access control -- a viewer can edit local storage. See
/// KNOWN_LIMITATIONS.md #8.
enum UserRole { user, admin }

class AuthSession {
  const AuthSession({required this.email, required this.role});

  final String email;
  final UserRole role;

  bool get isAdmin => role == UserRole.admin;
}

class AuthService {
  static const _savedEmailKey = 'auth.saved_email';
  static const _savedRoleKey = 'auth.saved_role';

  // Two mock accounts for the demo. Real authentication -- accounts, hashed
  // passwords, server-side sessions -- is explicitly out of scope and is the
  // top security gap recorded for handover.
  static const demoUsername = 'mandichatbot';
  static const demoPassword = 'mandichatbot123';
  static const adminUsername = 'mandiadmin';
  static const adminPassword = 'mandiadmin123';

  static const _accounts = <String, ({String password, UserRole role})>{
    demoUsername: (password: demoPassword, role: UserRole.user),
    adminUsername: (password: adminPassword, role: UserRole.admin),
  };

  Future<AuthSession?> restoreSession() async {
    final preferences = await SharedPreferences.getInstance();
    final email = preferences.getString(_savedEmailKey);
    if (email == null) return null;

    // Falls back to the LESSER privilege: a session saved before roles
    // existed, or one whose stored role we do not recognise, must never come
    // back as an admin.
    final role = _roleFromName(preferences.getString(_savedRoleKey));
    return AuthSession(email: email, role: role);
  }

  Future<AuthSession> signIn({
    required String email,
    required String password,
    required bool rememberMe,
  }) async {
    final normalizedEmail = email.trim().toLowerCase();
    final account = _accounts[normalizedEmail];

    if (account == null || account.password != password) {
      // One message for both cases, so the error does not reveal which
      // usernames exist.
      throw Exception('Invalid credentials. Please try again.');
    }

    if (rememberMe) {
      final preferences = await SharedPreferences.getInstance();
      await preferences.setString(_savedEmailKey, normalizedEmail);
      await preferences.setString(_savedRoleKey, account.role.name);
    } else {
      await signOut();
    }
    return AuthSession(email: normalizedEmail, role: account.role);
  }

  Future<void> signOut() async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_savedEmailKey);
    // Removed too: a leftover role key would promote the next person who signs
    // in without remember-me.
    await preferences.remove(_savedRoleKey);
  }

  static UserRole _roleFromName(String? name) {
    return name == UserRole.admin.name ? UserRole.admin : UserRole.user;
  }
}
