# Integrated local research demo

This branch combines community responses, offline translation, optional history
persistence, and shared-quotation grouping. It includes the rag.py merge resolution.

## First-time setup

From the repository root, create a Python 3.11 virtual environment:

    python3.11 -m venv .venv

Activate it on macOS/Linux:

    source .venv/bin/activate

Or in Windows PowerShell:

    .venv\Scripts\Activate.ps1

Install dependencies:

    python -m pip install -r requirements.txt -r requirements-translation.txt -r requirements-tts.txt

Configure your own .env using the project's configuration instructions.
Do not commit credentials, model weights, or confidential datasets.

Install/start Ollama and prepare the answer model:

    ollama pull mistral:7b

Ensure OLLAMA_MODEL=mistral:7b and OLLAMA_URL points to your intended Ollama
server. The default local endpoint is http://localhost:11434/api/generate.

## Download public model files once

These setup commands require internet. They download model files; use no
confidential text during setup. Unset HF_HUB_OFFLINE during downloading.

Download the translation model without the duplicate safetensors weights:

    python -c "from huggingface_hub import snapshot_download; snapshot_download('facebook/nllb-200-distilled-600M', allow_patterns=['*.json', '*.model', 'pytorch_model.bin'])"

Download Bangla speech into models/tts/bn:

    python prepare_tts.py --language bn

An existing speech installation can instead be reused by setting TTS_MODEL_DIR
to its model root containing bn/. LOCAL_TRANSLATION_MODEL can point to an
existing translation-model directory containing pytorch_model.bin.

Allow several GB of free disk space. See LOCAL_TRANSLATION_SETUP.md for the
NLLB research-use and licence limitations. This is not a production deployment.

## Start the backend

With the virtual environment active:

    python run_local_demo.py --check
    python run_local_demo.py

The launcher forces local translation, offline Hugging Face loading, enabled
backend speech, and a loopback API on port 8000. Stop any old API first if
that port is occupied. Checks verify files/dependencies, not translation quality.

The default dataset is the tracked public research CSV. A separately approved
local CSV can be selected with --kg. Do not commit that dataset.

## Start Flutter in a second terminal

    cd flutter_application
    flutter pub get
    flutter run -d chrome --dart-define=PERSIST_CHAT_HISTORY=false --dart-define=BACKEND_TTS_LANGUAGES=bn

Use the loopback API configuration. History persistence is disabled for this
build; existing stored history is not erased. This flag does not disable other
features such as feedback submission. Bangla uses backend speech; other voices
depend on the device. Microphone recognition is separate and is not guaranteed
local-only; use typed questions for this demo.

## Validation and remaining issues

Combined checks: 95 Python tests plus 9 subtests, and 100 Flutter tests passed.
Flutter analysis reported an existing informational lint in admin_service.dart.
Bangla read-aloud worked on the tested Mac after configuring the model path.

A language-question retest quoted the shared sentence once. Its opening still
said "primarily Garo" although the quotation supports both Bengali and Garo.
Unrelated housing source cards also appeared. These remain answer/retrieval
quality issues. The integration community-CSV and history-reload manual checks
have not yet been confirmed.

## Search multiple CSVs in one session

Repeat --kg to load research and approved local community CSVs into one index:

    python run_local_demo.py --kg data/production_graph/garo_1_kg_refined.csv --kg /path/to/local/community.csv

One --kg still loads one dataset. Without --kg, the launcher uses the Tangail
demo CSV. Repeated references to the same resolved file are loaded once.
Loaded records retain their metadata and receive unique process-local IDs.

CSV concept retrieval now filters identity-only matches when topic-matching
records exist. This corpus-specific heuristic applies to both source types;
it does not establish semantic relevance or change Neo4j retrieval.

Validation: 90 tests and 9 subtests passed. A local 625-record run answered the
research language question and preserved the six forest-management responses,
including record 01's "No", without switching datasets.

This does not automatically load the team's full research corpus. Supply its
approved CSV paths explicitly. Confidential CSVs remain local and must not
be committed. The existing model setup and research-prototype limitations apply.
