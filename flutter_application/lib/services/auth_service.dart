import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'api_config.dart';

class AuthException implements Exception {
  const AuthException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// What a signed-in person is allowed to see.
///
/// This decides which buttons render, nothing more. The admin upload endpoint
/// is protected server-side by ADMIN_UPLOAD_SECRET, because a role held in the
/// browser is not a access control -- a viewer can edit local storage. See
/// KNOWN_LIMITATIONS.md #8.
enum UserRole { user, admin }

class AuthSession {
  const AuthSession({
    required this.email,
    required this.role,
    required this.token,
  });

  final String email;
  final UserRole role;
  final String token;

  bool get isAdmin => role == UserRole.admin;
}

class RegistrationDetails {
  const RegistrationDetails({
    required this.username,
    required this.email,
    required this.phoneCountryCode,
    required this.phoneNumber,
    required this.password,
  });

  final String username;
  final String email;
  final String phoneCountryCode;
  final String phoneNumber;
  final String password;
}

class AuthService {
  AuthService({http.Client? client, String? endpoint})
    : _client = client ?? http.Client(),
      endpoint = endpoint ?? '$apiBaseUrl/auth';

  final http.Client _client;
  final String endpoint;
  static const _savedEmailKey = 'auth.saved_email';
  static const _savedRoleKey = 'auth.saved_role';
  static const _savedTokenKey = 'auth.saved_token';

  Future<AuthSession?> restoreSession() async {
    final preferences = await SharedPreferences.getInstance();
    final email = preferences.getString(_savedEmailKey);
    final token = preferences.getString(_savedTokenKey);
    if (email == null || token == null || token.isEmpty) return null;

    // Falls back to the LESSER privilege: a session saved before roles
    // existed, or one whose stored role we do not recognise, must never come
    // back as an admin.
    final role = _roleFromName(preferences.getString(_savedRoleKey));
    return AuthSession(email: email, role: role, token: token);
  }

  Future<AuthSession> signIn({
    required String email,
    required String password,
    required bool rememberMe,
  }) async {
    return _authenticate(
      path: 'login',
      email: email,
      password: password,
      rememberMe: rememberMe,
    );
  }

  Future<AuthSession> register({
    required RegistrationDetails details,
    required bool rememberMe,
  }) async {
    return _authenticate(
      path: 'register',
      email: details.email,
      password: details.password,
      rememberMe: rememberMe,
      registrationDetails: details,
    );
  }

  Future<AuthSession> _authenticate({
    required String path,
    required String email,
    required String password,
    required bool rememberMe,
    RegistrationDetails? registrationDetails,
  }) async {
    late final http.Response response;
    try {
      response = await _client
          .post(
            Uri.parse('${endpoint.replaceAll(RegExp(r'/$'), '')}/$path'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'email': email.trim(),
              'password': password,
              if (registrationDetails != null) ...{
                'username': registrationDetails.username.trim(),
                'phone_country_code': registrationDetails.phoneCountryCode,
                'phone_number': registrationDetails.phoneNumber.trim(),
              },
            }),
          )
          .timeout(const Duration(seconds: 15));
    } on Exception catch (error) {
      throw AuthException(
        'Cannot reach the authentication server at $endpoint. '
        'Start the API with "python rag.py --serve" and try again. '
        '($error)',
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw AuthException(_errorMessage(response.body));
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    final normalizedEmail = payload['email'] as String?;
    final token = payload['token'] as String?;
    if (normalizedEmail == null || token == null || token.isEmpty) {
      throw const AuthException('Authentication response was incomplete.');
    }
    final role = payload['role'] == UserRole.admin.name
        ? UserRole.admin
        : UserRole.user;
    if (rememberMe) {
      final preferences = await SharedPreferences.getInstance();
      await preferences.setString(_savedEmailKey, normalizedEmail);
      await preferences.setString(_savedRoleKey, role.name);
      await preferences.setString(_savedTokenKey, token);
    } else {
      await signOut();
    }
    return AuthSession(email: normalizedEmail, role: role, token: token);
  }

  Future<void> signOut() async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_savedEmailKey);
    // Removed too: a leftover role key would promote the next person who signs
    // in without remember-me.
    await preferences.remove(_savedRoleKey);
    await preferences.remove(_savedTokenKey);
  }

  static String _errorMessage(String body) {
    try {
      final payload = jsonDecode(body);
      if (payload is Map && payload['error'] is String) {
        return payload['error'] as String;
      }
    } catch (_) {
      // The caller still receives a useful generic error below.
    }
    return 'Authentication failed. Please try again.';
  }

  static UserRole _roleFromName(String? name) {
    return name == UserRole.admin.name ? UserRole.admin : UserRole.user;
  }
}
