import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_application/services/chat_history_service.dart';

void main() {
  test('disabled history makes no server requests', () async {
    final service = ChatHistoryService(
      persistHistory: false,
      authToken: 'fictional-token',
      client: MockClient((request) async {
        throw StateError('History must not contact the server');
      }),
    );

    expect(await service.load('demo@example.invalid'), isEmpty);
    await service.save('demo@example.invalid', []);
    await service.delete('demo@example.invalid', 'fictional-id');
    await service.clear('demo@example.invalid');
  });

  test('disabled history leaves existing local storage untouched', () async {
    const email = 'demo@example.invalid';
    final key =
        'chat.history.${base64Url.encode(utf8.encode(email.toLowerCase()))}';
    const stored = 'existing history sentinel';

    SharedPreferences.setMockInitialValues({key: stored});
    final service = ChatHistoryService(persistHistory: false);

    expect(await service.load(email), isEmpty);
    await service.save(email, []);
    await service.delete(email, 'fictional-id');
    await service.clear(email);

    final preferences = await SharedPreferences.getInstance();
    expect(preferences.getString(key), stored);
  });
}
