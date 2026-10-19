# SCRUM-367: local translation research prototype

The default provider is `local`: a cached NLLB-200 distilled 600M model translates
English, Bangla and Hindi. Runtime model/tokenizer loading uses local_files_only;
it never downloads a model or falls back to Google/MyMemory. Missing dependencies,
missing models, and incomplete generation return failure to existing API handling.
Selected answer translation failure uses the existing TranslationUnavailableError
response. Question failure retains the original question for the existing glossary
retrieval fallback; it does not establish that translation succeeded.

Install optional dependencies with:

    .venv/bin/python -m pip install -r requirements-translation.txt

The tested Mac already has cached model weights. The loader explicitly selects
pytorch_model.bin to avoid the failing safetensors conversion encountered during
this trial. No automatic download is performed. Set LOCAL_TRANSLATION_MODEL to a
local directory or predownloaded Hugging Face model ID. The default ID is
facebook/nllb-200-distilled-600M. Provision weights separately before starting.

Run the server with TRANSLATION_PROVIDER=local (remove older llm/auto overrides).
Explicit llm retains Ollama translation. Explicit auto/online/google can send text
to external translation services; use only where that data flow is permitted.
An unknown or blank provider selects local.

Token-aware chunks stay below 384 input tokens without truncating input. Blank
paragraphs are retained. A lock serialises model use and tokenizer source-language
changes. The model is loaded lazily once on CPU. Cache/model/dependency failures
are logged by exception type only. English API requests currently also precompute
Hindi/Bangla translations, so this change does not remove that latency.

Validation so far: three fictional English sentences translated to Bangla/Hindi;
four reverse-translation samples retained year, rainfall direction and negation.
These samples are not a general accuracy guarantee. Native-speaker review,
long-answer testing, selected-language API failure checks, and latency/memory
checks remain necessary. Stop other model processes on an 8 GB Mac during testing.

NLLB model card: https://huggingface.co/facebook/nllb-200-distilled-600M
Licence: CC-BY-NC-4.0. Intended for translation research, not released for production
deployment. This is a research prototype; choose an appropriate model/licence
before deployment. Do not commit model weights or confidential datasets.
