import 'package:speech_to_text/speech_to_text.dart';

/// Wraps speech_to_text so the composer can offer voice input without
/// exposing the plugin's initialization and callback details.
///
/// Voice input isn't supported on every platform (notably Windows/Linux
/// desktop today), so callers must check [isAvailable] after [init] and
/// hide the mic control when it's false rather than assuming it works.
class SpeechService {
  final SpeechToText _speech = SpeechToText();
  bool _isAvailable = false;

  bool get isAvailable => _isAvailable;
  bool get isListening => _speech.isListening;

  // Prepares the recognizer. [onListeningChanged] fires whenever
  // recognition starts or stops (including stopping on its own, e.g. after
  // silence or an error) so the UI can keep its mic icon in sync.
  Future<bool> init({
    required void Function(bool listening) onListeningChanged,
  }) async {
    _isAvailable = await _speech.initialize(
      onStatus: (status) => onListeningChanged(status == 'listening'),
      onError: (_) => onListeningChanged(false),
    );
    return _isAvailable;
  }

  // Starts listening, calling [onResult] with the live transcript as the
  // user speaks. No-ops if the recognizer isn't available.
  Future<void> listen(
    void Function(String text) onResult, {
    String languageCode = 'en',
  }) async {
    if (!_isAvailable) return;

    const localeIds = {'en': 'en_AU', 'hi': 'hi_IN', 'bn': 'bn_BD'};

    await _speech.listen(
      onResult: (result) => onResult(result.recognizedWords),
      listenOptions: SpeechListenOptions(
        localeId: localeIds[languageCode] ?? localeIds['en'],
      ),
    );
  }

  // Stops listening, if in progress.
  Future<void> stop() => _speech.stop();

  // Releases the recognizer.
  void dispose() {
    _speech.stop();
  }
}
