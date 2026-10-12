abstract interface class WebSpeechFallback {
  bool speak(
    String text,
    String locale, {
    required void Function() onDone,
    required void Function(String error) onError,
  });

  void stop();
}
