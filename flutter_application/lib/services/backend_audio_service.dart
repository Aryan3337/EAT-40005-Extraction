import 'dart:async';
import 'dart:convert';

import 'package:audioplayers/audioplayers.dart';
import 'package:http/http.dart' as http;

import 'api_config.dart';

abstract class BackendAudioPlayer {
  Stream<void> get completed;
  Future<void> play(String url);
  Future<void> stop();
  Future<void> dispose();
}

class _AudioPlayerAdapter implements BackendAudioPlayer {
  final AudioPlayer _player = AudioPlayer();
  @override
  Stream<void> get completed => _player.onPlayerComplete;
  @override
  Future<void> play(String url) => _player.play(UrlSource(url));
  @override
  Future<void> stop() => _player.stop();
  @override
  Future<void> dispose() => _player.dispose();
}

/// Generates and plays one bounded section at a time, preserving answer order.
class BackendAudioService {
  BackendAudioService({
    http.Client? client,
    BackendAudioPlayer? player,
    String? baseUrl,
    this.retryDelay = const Duration(seconds: 2),
  }) : _client = client ?? http.Client(),
       _player = player ?? _AudioPlayerAdapter(),
       _baseUrl = baseUrl ?? apiBaseUrl;

  final http.Client _client;
  final BackendAudioPlayer _player;
  final String _baseUrl;
  final Duration retryDelay;
  StreamSubscription<void>? _completion;
  Completer<void>? _playbackDone;
  Future<void> _requestTail = Future<void>.value();
  int _generation = 0;
  bool _disposed = false;

  static List<String> chunks(String text, {int limit = 450}) {
    if (limit < 2) throw ArgumentError.value(limit, 'limit');
    var remaining = text.trim();
    final result = <String>[];
    while (remaining.length > limit) {
      final prefix = remaining.substring(0, limit);
      final boundaries = RegExp(r'[।.!?\s]').allMatches(prefix).toList();
      var end = boundaries.isEmpty ? limit : boundaries.last.end;
      // Do not split a UTF-16 surrogate pair (e.g. an emoji).
      final last = remaining.codeUnitAt(end - 1);
      if (last >= 0xD800 && last <= 0xDBFF) end--;
      result.add(remaining.substring(0, end));
      remaining = remaining.substring(end);
    }
    if (remaining.isNotEmpty) result.add(remaining);
    return result;
  }

  bool _cancelled(int generation) => _disposed || generation != _generation;

  Future<http.Response?> _request(
    String text,
    String language,
    int generation,
  ) {
    // A stopped HTTP request may still be generating on the server. Wait for
    // it to finish before sending this service's next request.
    final job = _requestTail.then((_) async {
      for (var attempt = 0; attempt < 60; attempt++) {
        if (_cancelled(generation)) return null;
        final response = await _client
            .post(
              Uri.parse('$_baseUrl/tts'),
              headers: {'Content-Type': 'application/json'},
              body: jsonEncode({'text': text, 'language': language}),
            )
            .timeout(const Duration(seconds: 180));
        if (_cancelled(generation)) return null;
        if (response.statusCode != 429) return response;
        await Future<void>.delayed(retryDelay);
      }
      throw StateError('Speech engine is still busy. Please try again later.');
    });
    _requestTail = job.then<void>((_) {}, onError: (Object _) {});
    return job;
  }

  Future<bool> speak(
    String text,
    String language, {
    required void Function() onDone,
    required void Function(String) onError,
  }) async {
    final generation = ++_generation;
    _releasePlaybackWait();
    try {
      await _completion?.cancel();
      await _player.stop();
      if (_cancelled(generation)) return true;
      for (final section in chunks(text)) {
        if (section.trim().isEmpty) continue;
        final response = await _request(section, language, generation);
        if (response == null || _cancelled(generation)) return true;
        final payload = jsonDecode(response.body) as Map<String, dynamic>;
        if (response.statusCode != 200) {
          throw StateError(
            payload['error']?.toString() ?? 'Speech generation failed.',
          );
        }
        final path = payload['audio_path'];
        if (path is! String ||
            !RegExp(r'^/tts/audio/[a-f0-9]{32}\.wav$').hasMatch(path)) {
          throw StateError('The speech API returned an invalid audio path.');
        }
        final done = Completer<void>();
        _playbackDone = done;
        await _completion?.cancel();
        _completion = _player.completed.listen(
          (_) {
            if (!done.isCompleted) done.complete();
          },
          onError: (Object error) {
            if (!done.isCompleted) done.completeError(error);
          },
        );
        await _player.play('$_baseUrl$path');
        if (_cancelled(generation)) {
          await _player.stop();
          return true;
        }
        await done.future.timeout(const Duration(minutes: 5));
        if (_cancelled(generation)) return true;
      }
      if (!_cancelled(generation)) onDone();
      return true;
    } catch (error) {
      if (_cancelled(generation)) return true;
      onError('Backend speech: $error');
      onDone();
      return false;
    } finally {
      if (generation == _generation) {
        await _completion?.cancel();
        _completion = null;
        _playbackDone = null;
      }
    }
  }

  void _releasePlaybackWait() {
    final done = _playbackDone;
    if (done != null && !done.isCompleted) done.complete();
    _playbackDone = null;
  }

  Future<void> stop() async {
    ++_generation;
    _releasePlaybackWait();
    await _completion?.cancel();
    _completion = null;
    await _player.stop();
  }

  Future<void> dispose() async {
    _disposed = true;
    await stop();
    _client.close();
    await _player.dispose();
  }
}
