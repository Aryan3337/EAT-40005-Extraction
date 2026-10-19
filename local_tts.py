"""Optional, self-hosted MMS speech. Inference uses downloaded local files only.

Enable for local testing with TTS_ENABLED=1. Audio is retained briefly in RAM,
not written to disk. This prototype is not a public multi-user speech service.
"""
import io
import json
import os
import re
import struct
import threading
import time
import uuid
import wave
from pathlib import Path

MODELS = {'bn': 'facebook/mms-tts-ben', 'hi': 'facebook/mms-tts-hin',
          'en': 'facebook/mms-tts-eng'}
MAX_TEXT = 1500
MAX_BODY = 16000
MAX_AUDIO = 16 * 1024 * 1024


def validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object.')
    text = payload.get('text')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('text must be a non-empty string.')
    text = text.strip()
    if len(text) > MAX_TEXT:
        raise ValueError(f'Please read at most {MAX_TEXT} characters at a time.')
    language = payload.get('language', 'en')
    if not isinstance(language, str):
        raise ValueError('language must be en, hi or bn.')
    language = language.lower().replace('_', '-').split('-')[0]
    if language not in MODELS:
        raise ValueError('language must be en, hi or bn.')
    return text, language


def text_chunks(text, limit=250):
    """Bound model inputs without dropping any character in long answers."""
    while text:
        if len(text) <= limit:
            yield text
            return
        prefix = text[:limit]
        boundaries = [m.end() for m in re.finditer(r'[।.!?\s]', prefix)]
        split = boundaries[-1] if boundaries else limit
        yield text[:split]
        text = text[split:]


def wav_bytes(samples, sample_rate):
    if not samples or sample_rate <= 0:
        raise ValueError('Speech engine returned no audio.')
    data = io.BytesIO()
    with wave.open(data, 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        values = (max(-32768, min(32767, round(float(x) * 32767))) for x in samples)
        writer.writeframes(b''.join(struct.pack('<h', x) for x in values))
    result = data.getvalue()
    if len(result) > MAX_AUDIO:
        raise ValueError('Generated audio is too large. Try a shorter answer.')
    return result


class LocalMmsEngine:
    def __init__(self):
        self.models = {}

    def render(self, text, language):
        # Lazy imports: normal RAG operation needs no TTS packages.
        import torch
        from transformers import AutoTokenizer, VitsModel
        if language not in self.models:
            folder = Path(os.getenv('TTS_MODEL_DIR', 'models/tts')) / language
            if not folder.is_dir():
                raise RuntimeError('Download the requested TTS model with prepare_tts.py first.')
            tokenizer = AutoTokenizer.from_pretrained(str(folder), local_files_only=True)
            model = VitsModel.from_pretrained(str(folder), local_files_only=True).eval()
            self.models[language] = (tokenizer, model)
        tokenizer, model = self.models[language]
        rate = int(model.config.sampling_rate)
        samples = []
        for chunk in text_chunks(text):
            inputs = tokenizer(chunk, return_tensors='pt')
            if inputs['input_ids'].numel() == 0:
                continue
            with torch.inference_mode():
                speech = model(**inputs).waveform[0].cpu().tolist()
            samples.extend(speech)
            samples.extend([0.0] * int(rate * 0.12))
            if len(samples) * 2 > MAX_AUDIO - 44:
                raise ValueError('Generated audio is too large. Try a shorter answer.')
        return wav_bytes(samples, rate)


class TtsController:
    def __init__(self, engine=None, enabled=None, clock=time.monotonic):
        self.engine = engine or LocalMmsEngine()
        self.enabled = enabled
        self.clock = clock
        self.busy = threading.Lock()
        self.cache_lock = threading.Lock()
        self.audio = {}

    def synthesize(self, payload):
        enabled = self.enabled if self.enabled is not None else os.getenv('TTS_ENABLED') == '1'
        if not enabled:
            raise RuntimeError('Backend speech is disabled. Start the API with TTS_ENABLED=1.')
        text, language = validate_payload(payload)
        if not self.busy.acquire(blocking=False):
            raise BlockingIOError('Speech engine is busy. Please try again shortly.')
        try:
            audio = self.engine.render(text, language)
            if not audio or len(audio) > MAX_AUDIO:
                raise RuntimeError('Speech engine returned invalid audio.')
            token = uuid.uuid4().hex
            with self.cache_lock:
                self._prune()
                # Bound memory to three generated files, each at most 16 MiB.
                while len(self.audio) >= 3:
                    del self.audio[next(iter(self.audio))]
                self.audio[token] = (self.clock() + 300, audio)
            return {'audio_path': f'/tts/audio/{token}.wav', 'language': language}
        finally:
            self.busy.release()

    def _prune(self):
        for token, (expiry, _) in list(self.audio.items()):
            if expiry <= self.clock():
                del self.audio[token]

    def lookup(self, path):
        match = re.fullmatch(r'/tts/audio/([a-f0-9]{32})\.wav', path)
        if not match:
            return None
        with self.cache_lock:
            self._prune()
            entry = self.audio.get(match[1])
            return entry[1] if entry else None


controller = TtsController()


def handle_post(handler):
    try:
        length = int(handler.headers.get('Content-Length', '0'))
        if not 0 < length <= MAX_BODY:
            handler._send_json(413, {'error': 'Speech request is empty or too large.'})
            return
        payload = json.loads(handler.rfile.read(length))
        handler._send_json(200, controller.synthesize(payload))
    except BlockingIOError as error:
        handler._send_json(429, {'error': str(error)})
    except (ValueError, UnicodeError) as error:
        handler._send_json(400, {'error': str(error)})
    except RuntimeError as error:
        handler._send_json(503, {'error': str(error)})
    except Exception as error:
        # No request text or evidence is logged.
        print(f'Local TTS unavailable: {type(error).__name__}')
        handler._send_json(503, {'error': 'Local speech could not be generated. Check TTS installation and model setup.'})


def handle_audio(handler, head=False):
    audio = controller.lookup(handler.path)
    if audio is None:
        handler._send_json(404, {'error': 'Audio expired or not found. Click the speaker again.'})
        return
    handler.send_response(200)
    handler._send_cors_headers()
    handler.send_header('Content-Type', 'audio/wav')
    handler.send_header('Content-Length', str(len(audio)))
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    if not head:
        handler.wfile.write(audio)
