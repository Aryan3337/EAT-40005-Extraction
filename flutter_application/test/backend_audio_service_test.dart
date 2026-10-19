import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:flutter_application/services/backend_audio_service.dart';

class FakePlayer implements BackendAudioPlayer {
  final events = StreamController<void>.broadcast(sync: true);
  final urls = <String>[];
  bool finishAutomatically = true;
  @override
  Stream<void> get completed => events.stream;
  @override
  Future<void> play(String url) async {
    urls.add(url);
    if (finishAutomatically) scheduleMicrotask(() => events.add(null));
  }

  @override
  Future<void> stop() async {}
  @override
  Future<void> dispose() => events.close();
}

http.Response audioResponse(int id) => http.Response(
  jsonEncode({
    'audio_path': '/tts/audio/${id.toRadixString(16).padLeft(32, '0')}.wav',
  }),
  200,
);

void main() {
  test('long Bangla text is preserved in bounded chunks', () {
    final text = List.filled(90, 'গারো জনগণ বাংলাদেশে বাস করে। ').join().trim();
    final parts = BackendAudioService.chunks(text);
    expect(parts.join(), text);
    expect(parts.every((p) => p.length <= 450), isTrue);
    expect(parts.length, greaterThan(1));
    expect(BackendAudioService.chunks(''), isEmpty);
  });

  test('plays every section in order and completes once', () async {
    final player = FakePlayer();
    final sent = <String>[];
    var done = 0;
    final service = BackendAudioService(
      player: player,
      baseUrl: 'http://test',
      client: MockClient((request) async {
        final payload = jsonDecode(request.body) as Map<String, dynamic>;
        expect(payload['language'], 'bn');
        sent.add(payload['text'] as String);
        return audioResponse(sent.length);
      }),
    );
    final text = List.filled(70, 'গারো জনগণ বাংলাদেশে বাস করে। ').join().trim();
    expect(
      await service.speak(
        text,
        'bn',
        onDone: () => done++,
        onError: (e) => fail(e),
      ),
      isTrue,
    );
    expect(sent.join(), text);
    expect(player.urls.length, sent.length);
    expect(done, 1);
    await service.dispose();
  });

  test('stop while request is pending prevents stale playback', () async {
    final response = Completer<http.Response>();
    final started = Completer<void>();
    final player = FakePlayer();
    final service = BackendAudioService(
      player: player,
      baseUrl: 'http://test',
      client: MockClient((_) {
        started.complete();
        return response.future;
      }),
    );
    var done = 0;
    final pending = service.speak(
      'গারো',
      'bn',
      onDone: () => done++,
      onError: (e) => fail(e),
    );
    await started.future;
    await service.stop();
    response.complete(audioResponse(1));
    await pending;
    expect(player.urls, isEmpty);
    expect(done, 0);
    await service.dispose();
  });

  test('retries a busy response without duplicate playback', () async {
    var requests = 0;
    final player = FakePlayer();
    final service = BackendAudioService(
      player: player,
      baseUrl: 'http://test',
      retryDelay: Duration.zero,
      client: MockClient((_) async {
        requests++;
        return requests == 1
            ? http.Response('{"error":"busy"}', 429)
            : audioResponse(1);
      }),
    );
    expect(
      await service.speak('গারো', 'bn', onDone: () {}, onError: (e) => fail(e)),
      isTrue,
    );
    expect(requests, 2);
    expect(player.urls.length, 1);
    await service.dispose();
  });
}
