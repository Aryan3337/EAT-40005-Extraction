import 'dart:js_interop';

import 'package:web/web.dart' as web;

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
    final utterance = web.SpeechSynthesisUtterance(text)
      ..lang = locale
      ..rate = 0.58
      ..pitch = 1.0;

    final languageCode = locale.toLowerCase().split('-').first;
    for (final voice in web.window.speechSynthesis.getVoices().toDart) {
      final voiceLanguage = voice.lang.toLowerCase().replaceAll('_', '-');
      if (voiceLanguage == locale.toLowerCase() ||
          voiceLanguage == languageCode ||
          voiceLanguage.startsWith('$languageCode-')) {
        utterance.voice = voice;
        break;
      }
    }

    void finish() {
      if (requestId != _requestId) return;
      onDone();
    }

    utterance
      ..onend = ((JSAny? _) => finish()).toJS
      ..onerror = ((JSAny? _) {
        if (requestId != _requestId) return;
        onError('The browser could not synthesize speech for $locale.');
      }).toJS;

    web.window.speechSynthesis.speak(utterance);
    return true;
  }

  @override
  void stop() {
    _requestId++;
    web.window.speechSynthesis.cancel();
  }
}
