import 'dart:js_interop';

import 'package:web/web.dart' as web;

import 'speech_chunks.dart';
import 'web_speech_fallback.dart';

WebSpeechFallback createFallback() => _BrowserSpeechFallback();

class _BrowserSpeechFallback implements WebSpeechFallback {
  int _requestId = 0;

  @override
  bool speak(
    String text,
    String locale, {
    required void Function() onDone,
    required void Function(String error) onError,
  }) {
    final requestId = ++_requestId;
    web.window.speechSynthesis.cancel();

    web.SpeechSynthesisVoice? voice;
    final languageCode = locale.toLowerCase().split('-').first;
    for (final candidate in web.window.speechSynthesis.getVoices().toDart) {
      final voiceLanguage = candidate.lang.toLowerCase().replaceAll('_', '-');
      if (voiceLanguage == locale.toLowerCase() ||
          voiceLanguage == languageCode ||
          voiceLanguage.startsWith('$languageCode-')) {
        voice = candidate;
        break;
      }
    }

    // Chrome stops long utterances after about 15 seconds, so the answer is
    // read one sentence at a time, each starting when the previous ends.
    final chunks = speechChunks(text);
    void speakChunk(int index) {
      if (requestId != _requestId) return;
      if (index >= chunks.length) {
        onDone();
        return;
      }
      final utterance = web.SpeechSynthesisUtterance(chunks[index])
        ..lang = locale
        ..rate = 1.0 // the Web Speech API's normal pace
        ..pitch = 1.0;
      if (voice != null) utterance.voice = voice;
      utterance
        ..onend = ((JSAny? _) => speakChunk(index + 1)).toJS
        ..onerror = ((JSAny? _) {
          if (requestId != _requestId) return;
          onError('The browser could not synthesize speech for $locale.');
        }).toJS;
      web.window.speechSynthesis.speak(utterance);
    }

    speakChunk(0);
    return true;
  }

  @override
  void stop() {
    _requestId++;
    web.window.speechSynthesis.cancel();
  }
}
