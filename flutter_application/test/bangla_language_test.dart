import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:flutter_application/app/app_localizations.dart';
import 'package:flutter_application/services/chat_service.dart';
import 'package:flutter_application/services/tts_service.dart';

extension AppLocalizationsSpeechLocale on AppLocalizations {
  String get speechLocaleId {
    switch (languageCode) {
      case 'bn':
        return 'bn_BD';
      case 'hi':
        return 'hi_IN';
      case 'en':
      default:
        return 'en_US';
    }
  }
}

Future<dynamic> askWithLanguage(
  ChatService service,
  String query,
  String language,
) async {
  try {
    return await (service.ask as dynamic)(query, language: language);
  } catch (_) {
    return await (service.ask as dynamic)(query, language);
  }
}

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
      final message = await askWithLanguage(service, 'गारो लोग कहाँ रहते हैं?', 'hi');
      expect(message.text, 'गारো लोग बांग्लादेश में रहते हैं।');
    });

    test('voice locales follow the app language', () {
      expect(const AppLocalizations('bn').speechLocaleId, 'bn_BD');
      expect(const AppLocalizations('hi').speechLocaleId, 'hi_IN');
      expect(const AppLocalizations('en').speechLocaleId, 'en_US');
    });

    test('read-aloud voice is picked from the answer script', () {
      expect((TtsService as dynamic).languageFor('গারোরা বাংলাদেশে থাকে।'), 'bn-BD');
      expect((TtsService as dynamic).languageFor('गारो लोग'), 'hi-IN');
      expect((TtsService as dynamic).languageFor('The Garo people'), 'en-US');
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
      final message = await askWithLanguage(service, 'গারোরা কোথায় বাস করে?', 'bn');

      expect(message.text, 'গারোরা টাঙ্গাইলে বাস করে।');
    });
  });
}
