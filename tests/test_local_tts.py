import io
import json
import unittest
import wave
from unittest.mock import patch
import local_tts


class FakeEngine:
    def render(self, text, language):
        return local_tts.wav_bytes([0.0, 0.2, -0.2], 16000)


class Handler:
    def __init__(self, payload):
        raw = json.dumps(payload).encode()
        self.headers = {'Content-Length': str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.sent = None

    def _send_json(self, status, payload):
        self.sent = (status, payload)


class LocalTtsTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(local_tts.validate_payload({'text': ' গারো ', 'language': 'bn-BD'}), ('গারো', 'bn'))
        for payload in ([], {'text': ''}, {'text': 'x', 'language': 'fr'}, {'text': 'x' * 1501}):
            with self.assertRaises(ValueError): local_tts.validate_payload(payload)

    def test_chunks_preserve_entire_text(self):
        text = 'গারো জনগণ বাংলাদেশে বাস করে। ' * 30
        chunks = list(local_tts.text_chunks(text))
        self.assertEqual(''.join(chunks), text)
        self.assertTrue(all(len(x) <= 250 for x in chunks))

    def test_wav_is_pcm_mono(self):
        with wave.open(io.BytesIO(FakeEngine().render('', 'bn'))) as reader:
            self.assertEqual((reader.getnchannels(), reader.getsampwidth(), reader.getframerate()), (1, 2, 16000))
            self.assertEqual(reader.getnframes(), 3)

    def test_create_retrieve_expire(self):
        now = [0.0]
        service = local_tts.TtsController(FakeEngine(), True, lambda: now[0])
        result = service.synthesize({'text': 'গারো', 'language': 'bn'})
        self.assertTrue(service.lookup(result['audio_path']).startswith(b'RIFF'))
        now[0] = 301
        self.assertIsNone(service.lookup(result['audio_path']))

    def test_busy_and_disabled(self):
        with self.assertRaises(RuntimeError):
            local_tts.TtsController(FakeEngine(), False).synthesize({'text': 'x'})
        service = local_tts.TtsController(FakeEngine(), True)
        service.busy.acquire()
        with self.assertRaises(BlockingIOError):service.synthesize({'text': 'x'})

    def test_engine_failure_releases_lock(self):
        service = local_tts.TtsController(FakeEngine(), True)
        with patch.object(service.engine, 'render', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):service.synthesize({'text': 'x'})
        self.assertTrue(service.busy.acquire(blocking=False))

    def test_http_statuses(self):
        with patch.object(local_tts, 'controller', local_tts.TtsController(FakeEngine(), True)):
            handler = Handler({'text': 'গারো', 'language': 'bn'})
            local_tts.handle_post(handler)
            self.assertEqual(handler.sent[0], 200)
            handler = Handler({'text': '', 'language': 'bn'})
            local_tts.handle_post(handler)
            self.assertEqual(handler.sent[0], 400)

    def test_memory_is_bounded(self):
        service = local_tts.TtsController(FakeEngine(), True)
        first = service.synthesize({'text': 'first'})
        for _ in range(4):service.synthesize({'text': 'next'})
        self.assertEqual(len(service.audio), 3)
        self.assertIsNone(service.lookup(first['audio_path']))


if __name__ == '__main__':unittest.main()
