import 'dart:convert';

import 'package:http/http.dart' as http;

const testUser = 'user@example.com';
const testUserPassword = 'user-password-123';
const testAdmin = 'mandiadmin';
const testAdminPassword = 'mandiadmin123';

class TestAuthClient extends http.BaseClient {
  final requests = <Map<String, dynamic>>[];

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final payload = jsonDecode(
      await request.finalize().bytesToString(),
    ) as Map<String, dynamic>;
    requests.add(payload);
    final email = (payload['email'] as String? ?? '').trim().toLowerCase();
    final password = payload['password'] as String? ?? '';
    final isAdmin = email == testAdmin && password == testAdminPassword;
    final isUser = email == testUser && password == testUserPassword;
    final isRegistration = request.url.path.endsWith('/register');
    final valid = isAdmin || isUser || isRegistration;
    final body = valid
        ? jsonEncode({
            'email': email,
            'role': isAdmin ? 'admin' : 'user',
            'token': 'test-token-$email',
          })
        : jsonEncode({'error': 'Invalid credentials.'});
    return http.StreamedResponse(
      Stream.value(utf8.encode(body)),
      isRegistration && valid ? 201 : (valid ? 200 : 401),
      headers: {'content-type': 'application/json'},
    );
  }
}
