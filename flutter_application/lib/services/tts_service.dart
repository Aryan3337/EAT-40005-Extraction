import 'package:flutter_tts/flutter_tts.dart';

/// Wraps flutter_tts so the chat UI can read assistant answers aloud
/// without dealing with the plugin's callback API directly.
class TtsService {
  TtsService() {
    _tts
      ..setLanguage('en-US')
      ..setSpeechRate(0.58)
      ..setPitch(1.0);
  }

  final FlutterTts _tts = FlutterTts();

  // Speaks [text] aloud, cancelling anything already being read.
  Future<void> speak(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;
    await _tts.stop();
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
