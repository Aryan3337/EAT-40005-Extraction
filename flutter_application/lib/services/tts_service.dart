import 'package:flutter_tts/flutter_tts.dart';

/// Wraps flutter_tts so the chat UI can read assistant answers aloud
/// without dealing with the plugin's callback API directly.
class TtsService {
  TtsService() {
    _tts
      ..setSpeechRate(0.58)
      ..setPitch(1.0);
  }

  final FlutterTts _tts = FlutterTts();
  String _language = 'en-US';

  // Tries to infer the best TTS language for the text, while defaulting to the
  // current language when the text is plain English or no language can be detected.
  String languageFor(String text) {
    final normalized = text.toLowerCase();

    if (RegExp(r'[\u0600-\u06FF]').hasMatch(text)) return 'ar-SA';
    if (RegExp(r'[\u4e00-\u9fff\u3040-\u30ff]').hasMatch(text)) return 'zh-CN';
    if (RegExp(r'[àâçéèêëîïôûùüÿæœ]').hasMatch(normalized)) return 'fr-FR';
    if (RegExp(r'[äöüß]').hasMatch(normalized)) return 'de-DE';
    if (RegExp(r'[áéíóúñü¿¡]').hasMatch(normalized)) return 'es-ES';
    if (RegExp(r'[àèéìíîòóùú]').hasMatch(normalized)) return 'it-IT';
    if (RegExp(r'[ãõçáéíóúâêôàü]').hasMatch(normalized)) return 'pt-BR';

    return _language;
  }

  // Speaks [text] aloud, cancelling anything already being read.
  Future<void> speak(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;
    await _tts.stop();
    final language = languageFor(trimmed);
    if (language != _language) {
      // If the device has no voice for it, keep the current voice.
      try {
        await _tts.setLanguage(language);
        _language = language;
      } catch (_) {}
    }
    await _tts.speak(trimmed);
  }

  // Stops speech in progress, if any.
  Future<void> stop() => _tts.stop();

  // Calls [callback] when speech finishes, is stopped, or errors, so the
  // UI can reset whichever message it was highlighting as "speaking".
  void onDone(void Function() callback) {
    _tts.setCompletionHandler(callback);
    _tts.setCancelHandler(callback);
    _tts.setErrorHandler((_) => callback());
  }

  // Releases the underlying TTS engine.
  Future<void> dispose() => _tts.stop();
}
