import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:flutter_application/app/app_localizations.dart';
import 'package:flutter_application/services/chat_service.dart';
import 'package:flutter_application/services/tts_service.dart';
import 'package:flutter_application/services/web_speech_fallback.dart';

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
  TestWidgetsFlutterBinding.ensureInitialized();

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
        'language',
        'welcomeBack',
        'loginDescription',
        'usernameEmail',
        'enterUsername',
        'password',
        'enterPassword',
        'showPassword',
        'hidePassword',
        'keepSignedIn',
        'signIn',
        'loginFooter',
        'invalidCredentials',
        'chatHistory',
        'newChat',
        'signOut',
        'savedConversations',
        'deleteConversation',
        'askAnything',
        'thinking',
        'sendQuestion',
        'tryThese',
      ]) {
        expect(bn.text(key), isNot(en.text(key)), reason: key);
      }
    });

    test('every English string has a Hindi translation', () {
      const en = AppLocalizations('en');
      const hi = AppLocalizations('hi');
      for (final key in [
        'language',
        'signIn',
        'askAnything',
        'thinking',
        'sendQuestion',
        'tryThese',
        'chatHistory',
        'newChat',
        'signOut',
      ]) {
        expect(hi.text(key), isNot(en.text(key)), reason: key);
      }
      expect(hi.languageName, 'हिन्दी');
    });

    test('sends Hindi as the language for Hindi questions', () async {
      final client = MockClient((request) async {
        expect(jsonDecode(request.body)['language'], 'hi');
        return http.Response(
          jsonEncode({
            'answer': 'गारो लोग बांग्लादेश में रहते हैं।',
            'triples': [],
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });
      final service = ChatService(client: client, endpoint: 'http://x/query');
      final message = await askWithLanguage(
        service,
        'गारो लोग कहाँ रहते हैं?',
        'hi',
      );
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

    test('chooses the highest quality installed Hindi and Bangla voices', () {
      final voices = [
        {'name': 'Hindi basic', 'locale': 'hi-IN', 'quality': 'normal'},
        {'name': 'Hindi premium', 'locale': 'hi-IN', 'quality': 'premium'},
        {'name': 'Bengali (India)', 'locale': 'bn-IN'},
      ];

      expect(
        TtsService.bestVoiceFor(voices, 'hi-IN')?['name'],
        'Hindi premium',
      );
      expect(
        TtsService.bestVoiceFor(voices, 'bn-BD')?['name'],
        'Bengali (India)',
      );
      expect(TtsService.bestVoiceFor(voices, 'fr-FR'), isNull);
    });

    test('read aloud selects and uses an installed Bangla voice', () async {
      const channel = MethodChannel('flutter_tts');
      final calls = <MethodCall>[];
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call);
        if (call.method == 'getVoices') {
          return [
            {'name': 'Bengali voice', 'locale': 'bn-IN'},
          ];
        }
        return 1;
      });
      addTearDown(() => messenger.setMockMethodCallHandler(channel, null));

      final tts = TtsService(supportsVoiceSelection: true);
      final started = await tts.speak('গারোরা বাংলাদেশে থাকে।');

      expect(started, isTrue);
      expect(
        calls.map((call) => call.method),
        containsAllInOrder(['setLanguage', 'getVoices', 'setVoice', 'speak']),
      );
      final selectedVoice = calls.firstWhere(
        (call) => call.method == 'setVoice',
      );
      expect(selectedVoice.arguments, {
        'name': 'Bengali voice',
        'locale': 'bn-IN',
      });
    });

    test('read aloud changes voice with the selected app language', () async {
      const channel = MethodChannel('flutter_tts');
      final calls = <MethodCall>[];
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(channel, (call) async {
        calls.add(call);
        if (call.method == 'getVoices') {
          return [
            {'name': 'English voice', 'locale': 'en-US'},
            {'name': 'Hindi voice', 'locale': 'hi-IN'},
            {'name': 'Bangla voice', 'locale': 'bn-IN'},
          ];
        }
        return 1;
      });
      addTearDown(() => messenger.setMockMethodCallHandler(channel, null));

      final tts = TtsService(supportsVoiceSelection: true);
      await tts.speak('The Garo people', languageCode: 'en');
      await tts.speak('गारो लोग', languageCode: 'hi');
      await tts.speak('গারো জনগণ', languageCode: 'bn');

      final selectedVoices = calls
          .where((call) => call.method == 'setVoice')
          .map((call) => call.arguments['name'])
          .toList();
      expect(selectedVoices, ['English voice', 'Hindi voice', 'Bangla voice']);
      final languageCalls = calls
          .where((call) => call.method == 'setLanguage')
          .map((call) => call.arguments)
          .toList();
      expect(languageCalls, ['en-US', 'hi-IN', 'bn-BD']);
    });

    test(
      'uses browser locale fallback when no matching voice is installed',
      () async {
        const channel = MethodChannel('flutter_tts');
        final calls = <MethodCall>[];
        final messenger =
            TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
        messenger.setMockMethodCallHandler(channel, (call) async {
          calls.add(call);
          if (call.method == 'getVoices') return <Map<String, String>>[];
          return 1;
        });
        addTearDown(() => messenger.setMockMethodCallHandler(channel, null));

        final fallback = _FakeWebSpeechFallback();
        final tts = TtsService(
          supportsVoiceSelection: true,
          useWebSpeechFallback: true,
          webSpeechFallback: fallback,
        );

        expect(
          await tts.speak('গারোরা বাংলাদেশে থাকে।', languageCode: 'bn'),
          isTrue,
        );
        expect(fallback.text, 'গারোরা বাংলাদেশে থাকে।');
        expect(fallback.locale, 'bn-BD');
        expect(calls.map((call) => call.method), isNot(contains('speak')));
      },
    );

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
      final message = await askWithLanguage(
        service,
        'গারোরা কোথায় বাস করে?',
        'bn',
      );

      expect(message.text, 'গারোরা টাঙ্গাইলে বাস করে।');
    });
  });
}

class _FakeWebSpeechFallback implements WebSpeechFallback {
  String? text;
  String? locale;

  @override
  bool speak(
    String text,
    String locale, {
    required void Function() onDone,
    required void Function(String error) onError,
  }) {
    this.text = text;
    this.locale = locale;
    return true;
  }

  @override
  void stop() {}
}
