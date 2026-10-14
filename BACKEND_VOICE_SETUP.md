# Backend voice prototype

This prototype was prepared against dev commit 70f51075a514635d60460767edc3667a46709f77.
It is not yet validated for actual pronunciation or live Mac/Windows playback.
It changes no translation, retrieval, feedback or source-verification behaviour.
Backend speech is optional and off by default; the current native speech path remains available.

## What changes

- `POST /tts` receives `text` and `language` and generates speech locally.
- The response contains a random, temporary `/tts/audio/<id>.wav` URL.
- Flutter plays the WAV with audioplayers instead of an installed Bengali voice.
- The first trial enables this path for Bangla only. English and Hindi can use it after downloading their models.
- Model inference reads only local files; it never calls a hosted model service with answer text.
- At most three audio files are held in memory. URLs expire after five minutes; expired entries are removed on the next cache operation. No generated audio is written to disk by the API.
- One synthesis request runs at a time. Extra requests return 429 instead of loading more models concurrently. The text limit is 1500 characters; oversized answers show an error instead of silently truncating.

## 1 Apply to a separate branch on your Mac

Save and unzip backend-voice-prototype.zip in Downloads. Run:

```bash
cd ~/Documents/EAT-40005-Response-Verification
git status --short
git fetch origin
git switch -c sangeetha-backend-voice origin/dev
git apply --check ~/Downloads/backend-voice-prototype/backend-voice.patch
git apply ~/Downloads/backend-voice-prototype/backend-voice.patch
```

If status lists changed files, preserve them before switching. If the patch check fails, stop and supply the error and `git log -1 --oneline`; do not force the patch or reset dev. No commit, push or merge is required for the local test.

## 2 Test a short Bangla sample before integrating

Python 3.10 or later is needed. Your existing Python 3.11 environment is suitable.
Install only the optional TTS requirements initially:

```bash
.venv/bin/python -m pip install -r requirements-tts.txt
.venv/bin/python prepare_tts.py --language bn
.venv/bin/python prepare_tts.py --language bn --sample 'গারো জনগণ বাংলাদেশে বাস করে।' --output tts-sample-bn.wav
open tts-sample-bn.wav
```

The download step obtains a public model and tokenizer from Hugging Face. The sample step uses local weights only. Do not upload the model folder or sample to git; they are ignored.
Ask Nuren to listen for skipped letters, understandable words, place names and pronunciation. Do not accept a model solely because it makes sound. Stop here if speech quality is unsuitable. Start with this short standalone sample before running Ollama and the TTS model together on the 8 GB Mac.

## 3 Run the API with speech enabled

```bash
.venv/bin/python -m unittest discover -s tests -p test_local_tts.py -v
TTS_ENABLED=1 .venv/bin/python rag.py --kg data.csv --serve
```

Leave this terminal running. In a second terminal:

```bash
cd ~/Documents/EAT-40005-Response-Verification/flutter_application
flutter pub get
dart format lib/services/backend_audio_service.dart lib/services/tts_service.dart
flutter analyze
flutter test
flutter run -d chrome --dart-define=BACKEND_TTS_LANGUAGES=bn
```

Use the speaker button manually for a Bangla answer. The first request loads the model and can take longer. Generated audio still needs normal browser playback permission; if auto-read is blocked, click the speaker manually. `flutter pub get` regenerates the lockfile and plugin registrations; these generated changes should be included if the team eventually commits the feature.

## 4 Enable all three languages only after their samples pass

Download and test English and Hindi on the machine running the backend:

```bash
.venv/bin/python prepare_tts.py --language en
.venv/bin/python prepare_tts.py --language hi
.venv/bin/python prepare_tts.py --language en --sample 'The Garo people live in Bangladesh.' --output tts-sample-en.wav
.venv/bin/python prepare_tts.py --language hi --sample 'गारो लोग बांग्लादेश में रहते हैं।' --output tts-sample-hi.wav
```

Then run Flutter with:

```bash
flutter run -d chrome --dart-define=BACKEND_TTS_LANGUAGES=bn,hi,en
```

Each model is loaded once when its language is requested, so memory usage increases when all languages have been used. Measure performance on the intended backend machine before choosing a deployment.

## 5 Windows verification

Use the same patched commit and downloaded model setup. In Windows PowerShell, activate the project's Python environment, install requirements-tts.txt, download the required model, and start the API:

```powershell
python -m pip install -r requirements-tts.txt
python prepare_tts.py --language bn
$env:TTS_ENABLED = '1'
python rag.py --kg data.csv --serve
```

In a separate terminal, from flutter_application:

```powershell
flutter pub get
flutter analyze
flutter test
flutter run -d chrome --dart-define=BACKEND_TTS_LANGUAGES=bn
```

Alternatively, `flutter run -d windows --dart-define=BACKEND_TTS_LANGUAGES=bn` tests the native desktop application if the Windows Flutter build tools are already set up. Browser and desktop results must be recorded separately.
The backend model can run on one server while both clients play its audio, but remote access requires correct API_BASE_URL, network configuration and hosting setup. Merely opening a local localhost URL on another computer will not reach your Mac.

## Acceptance checks

Record the commit, platform, browser/app, language, result and actual error for each trial.
Check audible playback and correct pronunciation in each required language, stop during generation, stop during playback, switching between answers, unreachable API, expired audio URL and a long answer.
The code detects API errors; it cannot guarantee useful speech from an untested model.

## Validation completed here

- Eight standard-library backend tests passed: validation, full-text chunking, WAV encoding, expiry, bounded memory, busy/disabled handling, lock release and POST response status.
- Four mounted HTTP route checks passed with a fake speech engine: POST generation, GET audio, HEAD audio and OPTIONS/CORS.
- Python syntax parsing passed for rag.py, local_tts.py and prepare_tts.py.
- The patch was checked against the uploaded snapshot.
- No actual MMS inference, model download, Flutter compilation or Mac/Windows playback was run in this environment. The required runtimes/models are unavailable here.

## Scope and model terms

This is a local academic prototype, not a finished hosted service. Before exposing /tts publicly, implement appropriate service access controls and rate limits. For the first test keep the existing loopback API binding.
MMS model cards identify the model license as CC BY NC 4.0. Retain attribution and review suitability before any commercial use. Sources:

- Meta Bengali model: https://huggingface.co/facebook/mms-tts-ben
- Meta Hindi model: https://huggingface.co/facebook/mms-tts-hin
- Meta English model: https://huggingface.co/facebook/mms-tts-eng
- Local VITS usage and uroman: https://huggingface.co/docs/transformers/model_doc/vits
- Audio playback package: https://pub.dev/packages/audioplayers

The reported ListTile assertion concerns the chat-history UI. This patch does not attempt a UI fix from a partial stack trace; provide the full first exception if it persists.
