import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

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
}
