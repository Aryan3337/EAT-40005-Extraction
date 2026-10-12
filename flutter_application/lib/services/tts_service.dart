import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_tts/flutter_tts.dart';

import 'web_speech_fallback.dart';
import 'backend_audio_service.dart';
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
      ..setSpeechRate(0.58)
      ..setPitch(1.0);
  }

  final FlutterTts _tts = FlutterTts();
  final bool? _supportsVoiceSelectionOverride;
  final bool? _useWebSpeechFallbackOverride;
  final WebSpeechFallback _webSpeechFallback;
  String _language = 'en-US';
  BackendAudioService? _backendAudio;
  bool _backendActive = false;
  static const _backendLanguages = String.fromEnvironment(
    'BACKEND_TTS_LANGUAGES',
    defaultValue: '',
  );
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
      return (_requiresNetwork(left) ? 1 : 0).compareTo(
        _requiresNetwork(right) ? 1 : 0,
      );
    });
    return voices.first;
  }

  // Speaks [text] aloud, cancelling anything already being read.
  Future<bool> speak(String text, {String? languageCode}) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return true;
    final requestId = ++_speechRequestId;
    final language = languageCode == null
        ? languageFor(trimmed, fallbackLanguage: _language)
        : localeForLanguage(languageCode);
    final code = _normalizeLocale(language).split('-').first;
    if (_backendLanguages.split(',').map((s) => s.trim()).contains(code)) {
      _backendActive = true;
      await _tts.stop();
      if (_useWebSpeechFallback) _webSpeechFallback.stop();
      if (requestId != _speechRequestId) return true;
      _backendAudio ??= BackendAudioService();
      return _backendAudio!.speak(
        trimmed,
        code,
        onDone: () {
          if (requestId == _speechRequestId) {
            _backendActive = false;
            _completionCallback();
          }
        },
        onError: (error) {
          if (requestId == _speechRequestId) _speechErrorCallback?.call(error);
        },
      );
    }
    await _backendAudio?.stop();
    await _tts.stop();
    _backendActive = false;
    if (requestId != _speechRequestId) return true;
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
    final result = await _tts.speak(trimmed);
    return voiceAvailable && result != 0;
  }

  // Stops speech in progress, if any.
  Future<void> stop() async {
    _speechRequestId++;
    if (_useWebSpeechFallback) _webSpeechFallback.stop();
    await _backendAudio?.stop();
    await _tts.stop();
  }

  // Calls [callback] when speech finishes, is stopped, or errors, so the
  // UI can reset whichever message it was highlighting.
  void onDone(
    void Function() callback, {
    void Function(String error)? onError,
  }) {
    _completionCallback = callback;
    _speechErrorCallback = onError;
    _tts.setCompletionHandler(() {
      if (!_backendActive) callback();
    });
    _tts.setCancelHandler(() {
      if (!_backendActive) callback();
    });
    _tts.setErrorHandler((error) {
      if (_backendActive) return;
      onError?.call(error.toString());
      callback();
    });
  }

  // Releases the underlying TTS engine.
  Future<void> dispose() async {
    _speechRequestId++;
    await _backendAudio?.dispose();
    await _tts.stop();
  }

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
