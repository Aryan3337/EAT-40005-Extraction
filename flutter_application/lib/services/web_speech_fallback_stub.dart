import 'web_speech_fallback.dart';

WebSpeechFallback createFallback() => _UnsupportedWebSpeechFallback();

class _UnsupportedWebSpeechFallback implements WebSpeechFallback {
  @override
  bool speak(
    String text,
    String locale, {
    required void Function() onDone,
    required void Function(String error) onError,
  }) => false;

  @override
  void stop() {}
}
