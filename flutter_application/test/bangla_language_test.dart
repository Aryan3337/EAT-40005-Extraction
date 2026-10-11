import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:flutter_application/app/app_localizations.dart';
import 'package:flutter_application/services/chat_service.dart';
import 'package:flutter_application/services/tts_service.dart';

void main() {
  group('Bangla language', () {
    test('keeps English and Hindi and adds Bangla', () {
      expect(AppLocalizations.supportedLanguageCodes, ['en', 'hi', 'bn']);
      expect(const AppLocalizations('en').text('signIn'), 'Sign in');
      expect(const AppLocalizations('hi').text('signIn'), 'साइन इन');
      expect(const AppLocalizations('bn').text('signIn'), 'সাইন ইন');
      expect(const AppLocalizations('bn').languageName, 'বাংলা');
    });

    test('every English string has a Bangla translation', () {
      const en = AppLocalizations('en');
      const bn = AppLocalizations('bn');
      for (final key in [
        'language', 'welcomeBack', 'loginDescription', 'usernameEmail',
        'enterUsername', 'password', 'enterPassword', 'showPassword',
        'hidePassword', 'keepSignedIn', 'signIn', 'loginFooter',
        'invalidCredentials', 'chatHistory', 'newChat', 'signOut',
        'savedConversations', 'deleteConversation', 'askAnything',
        'thinking', 'sendQuestion', 'tryThese',
      ]) {
        expect(bn.text(key), isNot(en.text(key)), reason: key);
      }
    });

    test('every English string has a Hindi translation', () {
      const en = AppLocalizations('en');
      const hi = AppLocalizations('hi');
      for (final key in [
        'language', 'signIn', 'askAnything', 'thinking', 'sendQuestion',
        'tryThese', 'chatHistory', 'newChat', 'signOut',
      ]) {
        expect(hi.text(key), isNot(en.text(key)), reason: key);
      }
      expect(hi.languageName, 'हिन्दी');
    });

    test('sends Hindi as the language for Hindi questions', () async {
      final client = MockClient((request) async {
        expect(jsonDecode(request.body)['language'], 'hi');
        return http.Response(
          jsonEncode({'answer': 'गारो लोग बांग्लादेश में रहते हैं।', 'triples': []}),
          200,
          headers: {'content-type': 'application/json'},
        );
      });
      final service = ChatService(client: client, endpoint: 'http://x/query');
      final message = await service.ask('गारो लोग कहाँ रहते हैं?', language: 'hi');
      expect(message.text, 'गारो लोग बांग्लादेश में रहते हैं।');
    });

    test('voice locales follow the app language', () {
      expect(const AppLocalizations('bn').speechLocaleId, 'bn_BD');
      expect(const AppLocalizations('hi').speechLocaleId, 'hi_IN');
      expect(const AppLocalizations('en').speechLocaleId, 'en_US');
    });

    test('read-aloud voice is picked from the answer script', () {
      expect(TtsService.languageFor('গারোরা বাংলাদেশে থাকে।'), 'bn-BD');
      expect(TtsService.languageFor('गारो लोग'), 'hi-IN');
      expect(TtsService.languageFor('The Garo people'), 'en-US');
    });

    test('sends the chosen language with the question', () async {
      final client = MockClient((request) async {
        expect(jsonDecode(request.body), {
          'query': 'গারোরা কোথায় বাস করে?',
          'language': 'bn',
        });
        return http.Response(
          jsonEncode({'answer': 'গারোরা টাঙ্গাইলে বাস করে।', 'triples': []}),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final service = ChatService(client: client, endpoint: 'http://x/query');
      final message = await service.ask('গারোরা কোথায় বাস করে?', language: 'bn');

      expect(message.text, 'গারোরা টাঙ্গাইলে বাস করে।');
    });
  });
}
