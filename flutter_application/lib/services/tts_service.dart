import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_tts/flutter_tts.dart';

import 'speech_chunks.dart';
import 'web_speech_fallback.dart';
import 'web_speech_fallback_stub.dart'
    if (dart.library.js_interop) 'web_speech_fallback_web.dart'
    as platform;

/// Wraps flutter_tts so the chat UI can read assistant answers aloud
/// without dealing with the plugin's callback API directly.
class TtsService {
  TtsService({
    bool? supportsVoiceSelection,
    bool? useWebSpeechFallback,
    WebSpeechFallback? webSpeechFallback,
  }) : _supportsVoiceSelectionOverride = supportsVoiceSelection,
       _useWebSpeechFallbackOverride = useWebSpeechFallback,
       _webSpeechFallback = webSpeechFallback ?? platform.createFallback() {
    _tts
      ..setSpeechRate(defaultSpeechRate)
      ..setPitch(1.0)
      // Each sentence is spoken only after the previous one has finished.
      ..awaitSpeakCompletion(true);
  }

  // A normal speaking pace. The scale differs per platform: the browser's
  // Web Speech API treats 1.0 as normal, while Android and Apple voices treat
  // 0.5 as normal. The old fixed 0.58 made web speech noticeably slow.
  static double get defaultSpeechRate {
    if (kIsWeb) return 1.0;
    return switch (defaultTargetPlatform) {
      TargetPlatform.android ||
      TargetPlatform.iOS ||
      TargetPlatform.macOS => 0.5,
      _ => 1.0,
    };
  }

  // True while an answer is being read sentence by sentence, so the engine's
  // per-sentence completion events do not end the read-aloud early.
  bool _readingChunks = false;

  final FlutterTts _tts = FlutterTts();
  final bool? _supportsVoiceSelectionOverride;
  final bool? _useWebSpeechFallbackOverride;
  final WebSpeechFallback _webSpeechFallback;
  String _language = 'en-US';
  int _speechRequestId = 0;
  void Function() _completionCallback = () {};
  void Function(String error)? _speechErrorCallback;

  static String languageFor(String text, {String fallbackLanguage = 'en-US'}) {
    final normalized = text.toLowerCase();

    if (RegExp(r'[\u0980-\u09FF]').hasMatch(text)) return 'bn-BD';
    if (RegExp(r'[\u0900-\u097F]').hasMatch(text)) return 'hi-IN';
    if (RegExp(r'[\u0600-\u06FF]').hasMatch(text)) return 'ar-SA';
    if (RegExp(r'[\u4e00-\u9fff\u3040-\u30ff]').hasMatch(text)) return 'zh-CN';
    if (RegExp(r'[àâçéèêëîïôûùüÿæœ]').hasMatch(normalized)) return 'fr-FR';
    if (RegExp(r'[äöüß]').hasMatch(normalized)) return 'de-DE';
    if (RegExp(r'[áéíóúñü¿¡]').hasMatch(normalized)) return 'es-ES';
    if (RegExp(r'[àèéìíîòóùú]').hasMatch(normalized)) return 'it-IT';
    if (RegExp(r'[ãõçáéíóúâêôàü]').hasMatch(normalized)) return 'pt-BR';

    return fallbackLanguage;
  }

  // Browser voices can load after startup, so resolve the installed voice
  // whenever the user asks the app to read an answer.
  Future<bool> setLanguage(String locale) async {
    try {
      await _tts.setLanguage(locale);
      _language = locale;

      if (!_supportsVoiceSelection) return true;
      final attempts = kIsWeb ? 4 : 1;
      for (var attempt = 0; attempt < attempts; attempt++) {
        final available = await _tts.getVoices;
        if (available is List) {
          final voice = bestVoiceFor(available, locale);
          final name = voice?['name']?.toString();
          final voiceLocale = voice?['locale']?.toString();
          if (name != null &&
              name.isNotEmpty &&
              voiceLocale != null &&
              voiceLocale.isNotEmpty) {
            await _tts.setVoice({'name': name, 'locale': voiceLocale});
            return true;
          }
        }
        if (kIsWeb && attempt < attempts - 1) {
          await Future<void>.delayed(const Duration(milliseconds: 150));
        }
      }
      return false;
    } on PlatformException catch (error) {
      debugPrint('Could not select the $locale speech voice: ${error.message}');
      return false;
    } on MissingPluginException catch (error) {
      debugPrint('Speech voice selection is unavailable: ${error.message}');
      return false;
    }
  }

  static Map<String, dynamic>? bestVoiceFor(
    Iterable<dynamic> available,
    String locale,
  ) {
    final normalizedLocale = _normalizeLocale(locale);
    final voices = available
        .whereType<Map>()
        .map((voice) => Map<String, dynamic>.from(voice))
        .where((voice) {
          final voiceLocale = _normalizeLocale(
            voice['locale']?.toString() ?? '',
          );
          final languageCode = normalizedLocale.split('-').first;
          return voiceLocale == normalizedLocale ||
              voiceLocale == languageCode ||
              voiceLocale.startsWith('$languageCode-');
        })
        .toList();
    if (voices.isEmpty) return null;

    voices.sort((left, right) {
      final quality = _quality(right).compareTo(_quality(left));
      if (quality != 0) return quality;
      // Natural/neural voices (Edge's "Online (Natural)", Chrome's "Google"
      // voices) sound far less robotic than the old built-in ones.
      final natural = _naturalness(right).compareTo(_naturalness(left));
      if (natural != 0) return natural;
      final exact = _exactLocale(right, normalizedLocale).compareTo(
        _exactLocale(left, normalizedLocale),
      );
      if (exact != 0) return exact;
      return (_requiresNetwork(left) ? 1 : 0).compareTo(
        _requiresNetwork(right) ? 1 : 0,
      );
    });
    return voices.first;
  }

  static int _naturalness(Map<String, dynamic> voice) {
    final name = (voice['name'] ?? '').toString().toLowerCase();
    if (name.contains('natural') || name.contains('neural')) return 2;
    if (name.contains('online') || name.startsWith('google')) return 1;
    return 0;
  }

  static int _exactLocale(Map<String, dynamic> voice, String locale) =>
      _normalizeLocale(voice['locale']?.toString() ?? '') == locale ? 1 : 0;

  // Speaks [text] aloud, cancelling anything already being read.
  Future<bool> speak(String text, {String? languageCode}) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return true;
    final requestId = ++_speechRequestId;
    await _tts.stop();
    if (requestId != _speechRequestId) return true;
    final language = languageCode == null
        ? languageFor(trimmed, fallbackLanguage: _language)
        : localeForLanguage(languageCode);
    final voiceAvailable = await setLanguage(language);
    if (requestId != _speechRequestId) return true;
    if (_useWebSpeechFallback && !voiceAvailable) {
      return _webSpeechFallback.speak(
        trimmed,
        language,
        onDone: _completionCallback,
        onError: (error) {
          _speechErrorCallback?.call(error);
          _completionCallback();
        },
      );
    }
    // Read one sentence at a time: one long utterance gets cut off or
    // garbled (skipped letters) by flutter_tts and the Web Speech API.
    final chunks = speechChunks(trimmed);
    // The plugin's result is 1 (started) or 0 (failed) on most platforms, but
    // the web version returns null when it waits for completion, so it must
    // not be typed as int (that threw after the first sentence in Edge).
    Object? result = 1;
    _readingChunks = true;
    try {
      for (final chunk in chunks) {
        if (requestId != _speechRequestId) return true; // stopped or replaced
        result = await _tts.speak(chunk);
        if (result == 0) break;
      }
    } finally {
      if (requestId == _speechRequestId) _readingChunks = false;
    }
    if (requestId == _speechRequestId) _completionCallback();
    return voiceAvailable && result != 0;
  }

  // Stops speech in progress, if any.
  Future<void> stop() {
    _speechRequestId++;
    _readingChunks = false;
    if (_useWebSpeechFallback) _webSpeechFallback.stop();
    return _tts.stop();
  }

  // Calls [callback] when speech finishes, is stopped, or errors, so the
  // UI can reset whichever message it was highlighting.
  void onDone(
    void Function() callback, {
    void Function(String error)? onError,
  }) {
    _completionCallback = callback;
    _speechErrorCallback = onError;
    // While reading sentence by sentence, speak() reports the end itself once
    // the last sentence is done; a single sentence's completion is ignored.
    _tts.setCompletionHandler(() {
      if (!_readingChunks) callback();
    });
    _tts.setCancelHandler(() {
      _readingChunks = false;
      callback();
    });
    _tts.setErrorHandler((error) {
      _readingChunks = false;
      onError?.call(error.toString());
      callback();
    });
  }

  // Releases the underlying TTS engine.
  Future<void> dispose() => _tts.stop();

  bool get _useWebSpeechFallback => _useWebSpeechFallbackOverride ?? kIsWeb;

  bool get _supportsVoiceSelection =>
      _supportsVoiceSelectionOverride ??
      (kIsWeb ||
          {
            TargetPlatform.android,
            TargetPlatform.iOS,
            TargetPlatform.macOS,
            TargetPlatform.windows,
          }.contains(defaultTargetPlatform));

  static String localeForLanguage(String languageCode) {
    final normalized = _normalizeLocale(languageCode);
    return switch (normalized.split('-').first) {
      'hi' => 'hi-IN',
      'bn' => 'bn-BD',
      'en' => 'en-US',
      _ => normalized,
    };
  }

  static String _normalizeLocale(String locale) =>
      locale.trim().toLowerCase().replaceAll('_', '-');

  static int _quality(Map<String, dynamic> voice) {
    final quality = voice['quality'];
    if (quality is num) return quality.toInt();
    return switch (quality?.toString().toLowerCase()) {
      'premium' => 4,
      'enhanced' => 3,
      'high' => 2,
      'normal' => 1,
      _ => 0,
    };
  }

  static bool _requiresNetwork(Map<String, dynamic> voice) =>
      voice['network_required'] == true ||
      voice['network_required']?.toString().toLowerCase() == 'true';
}
