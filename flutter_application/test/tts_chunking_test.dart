import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application/services/pronunciation.dart';
import 'package:flutter_application/services/speech_chunks.dart';
import 'package:flutter_application/services/tts_service.dart';

// SCRUM-370: answers are read one sentence at a time at a normal pace.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  String withoutSpaces(String text) => text.replaceAll(RegExp(r'\s'), '');

  group('speechChunks', () {
    test('splits Bangla, Hindi and English sentences', () {
      expect(
        speechChunks('গারোরা বাংলাদেশে থাকে। তারা মান্দি ভাষায় কথা বলে।'),
        ['গারোরা বাংলাদেশে থাকে।', 'তারা মান্দি ভাষায় কথা বলে।'],
      );
      expect(speechChunks('गारो लोग। वे मेघालय में रहते हैं।'), [
        'गारो लोग।',
        'वे मेघालय में रहते हैं।',
      ]);
      expect(speechChunks('First one. Second one!\n\nThird?'), [
        'First one.',
        'Second one!',
        'Third?',
      ]);
    });

    test('does not split numbers like 0.5 or 3.2', () {
      expect(speechChunks('About 0.5 percent. Then 3.2 more.'), [
        'About 0.5 percent.',
        'Then 3.2 more.',
      ]);
    });

    test('long sentences are split at commas or spaces, losing nothing', () {
      final long = List.filled(40, 'গারো জনগণ, মান্দি ভাষা').join(' ');
      final chunks = speechChunks(long, maxLength: 120);
      expect(chunks.length, greaterThan(1));
      expect(chunks.every((chunk) => chunk.length <= 120), isTrue);
      expect(withoutSpaces(chunks.join()), withoutSpaces(long));
    });

    test('empty text gives no chunks', () {
      expect(speechChunks('   \n  '), isEmpty);
    });
  });

  test('natural voices are preferred over robotic built-in ones', () {
    final voices = [
      {'name': 'Microsoft David - English (United States)', 'locale': 'en-US'},
      {
        'name': 'Microsoft Aria Online (Natural) - English (United States)',
        'locale': 'en-US',
      },
      {'name': 'Google US English', 'locale': 'en-US'},
      {
        'name': 'Microsoft Tanishaa Online (Natural) - Bengali (India)',
        'locale': 'bn-IN',
      },
      {
        'name': 'Microsoft Nabanita Online (Natural) - Bangla (Bangladesh)',
        'locale': 'bn-BD',
      },
    ];
    expect(
      TtsService.bestVoiceFor(voices, 'en-US')?['name'],
      'Microsoft Aria Online (Natural) - English (United States)',
    );
    // Both Bangla voices are natural; the Bangladesh one matches exactly.
    expect(
      TtsService.bestVoiceFor(voices, 'bn-BD')?['name'],
      'Microsoft Nabanita Online (Natural) - Bangla (Bangladesh)',
    );
  });

  test('web speech uses the normal 1.0 rate, not the old slow 0.58', () {
    if (kIsWeb) expect(TtsService.defaultSpeechRate, 1.0);
    expect(TtsService.defaultSpeechRate, isNot(0.58));
  });

  test('a long answer is spoken sentence by sentence, then done once', () async {
    const channel = MethodChannel('flutter_tts');
    final spoken = <String>[];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'speak') spoken.add(call.arguments as String);
      if (call.method == 'getVoices') {
        return [
          {'name': 'Bangla voice', 'locale': 'bn-BD'},
        ];
      }
      return 1;
    });
    addTearDown(() => messenger.setMockMethodCallHandler(channel, null));

    var doneCount = 0;
    final tts = TtsService(supportsVoiceSelection: true)
      ..onDone(() => doneCount++);
    final started = await tts.speak(
      'গারোরা বাংলাদেশে থাকে। তারা মান্দি ভাষায় কথা বলে।\n\nজনসংখ্যা প্রায় তিন লাখ।',
      languageCode: 'bn',
    );

    expect(started, isTrue);
    expect(spoken, [
      'গারোরা বাংলাদেশে থাকে।',
      'তারা মান্দি ভাষায় কথা বলে।',
      'জনসংখ্যা প্রায় তিন লাখ।',
    ]);
    expect(doneCount, 1);
  });

  test('keeps reading when the engine returns null (web)', () async {
    const channel = MethodChannel('flutter_tts');
    final spoken = <String>[];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'speak') {
        spoken.add(call.arguments as String);
        return null; // what flutter_tts web returns after awaiting completion
      }
      if (call.method == 'getVoices') {
        return [
          {'name': 'English voice', 'locale': 'en-US'},
        ];
      }
      return 1;
    });
    addTearDown(() => messenger.setMockMethodCallHandler(channel, null));

    final tts = TtsService(supportsVoiceSelection: true);
    final started = await tts.speak(
      'They live in India and Bangladesh. They speak Garo. It uses Roman letters.',
      languageCode: 'en',
    );

    expect(started, isTrue);
    expect(spoken, [
      'They live in India and Bangladesh.',
      'They speak Garo.',
      'It uses Roman letters.',
    ]);
  });

  group('pronunciation', () {
    test('Bangla words with হ্য are respelled for the voice', () {
      expect(
        forSpeech('ঐতিহ্যগত ওষুধ এবং ঐতিহ্যবাহী জ্ঞান।', 'bn-BD'),
        'ওইতিজ্ঝোগতো ওষুধ এবং ওইতিজ্ঝোবাহী জ্ঞান।',
      );
    });

    test('other languages are left alone', () {
      expect(forSpeech('ঐতিহ্যগত', 'en-US'), 'ঐতিহ্যগত');
    });

    test('the respelled text is what the voice receives', () async {
      const channel = MethodChannel('flutter_tts');
      final spoken = <String>[];
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(channel, (call) async {
        if (call.method == 'speak') spoken.add(call.arguments as String);
        if (call.method == 'getVoices') {
          return [
            {'name': 'Bangla voice', 'locale': 'bn-BD'},
          ];
        }
        return 1;
      });
      addTearDown(() => messenger.setMockMethodCallHandler(channel, null));

      await TtsService(
        supportsVoiceSelection: true,
      ).speak('উপসংহারে, ঐতিহ্যগত ওষুধ।', languageCode: 'bn');
      expect(spoken, ['উপসংহারে, ওইতিজ্ঝোগতো ওষুধ।']);
    });
  });
}
