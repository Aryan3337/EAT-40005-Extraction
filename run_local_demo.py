"""Start the integrated local research demo; never download models."""
import argparse
import importlib.util
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
parser.add_argument("--kg", action="append", help="CSV path; repeat to search multiple files")
args = parser.parse_args()

def fail(message):
    raise SystemExit(message)

for module in ("dotenv", "torch", "transformers", "sentencepiece", "uroman"):
    if importlib.util.find_spec(module) is None:
        fail(
            f"Missing dependency: {module}. Install requirements.txt, "
            "requirements-translation.txt and requirements-tts.txt."
        )

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

os.environ["TRANSLATION_PROVIDER"] = "local"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TTS_ENABLED"] = "1"

tts_root = Path(os.getenv("TTS_MODEL_DIR", str(ROOT / "models" / "tts"))).expanduser()
if not tts_root.is_absolute():
    tts_root = ROOT / tts_root
os.environ["TTS_MODEL_DIR"] = str(tts_root)
speech = tts_root / "bn"
if not (speech / "config.json").is_file() or not any(
    (speech / name).is_file()
    for name in ("model.safetensors", "pytorch_model.bin")
):
    fail(
        "Bangla speech model is missing. Run python prepare_tts.py "
        "--language bn during setup, or set TTS_MODEL_DIR to an existing "
        "model root containing the bn folder."
    )

from transformers.utils.hub import cached_file

location = os.getenv(
    "LOCAL_TRANSLATION_MODEL", "facebook/nllb-200-distilled-600M"
)
try:
    cached_file(location, "pytorch_model.bin", local_files_only=True)
except Exception:
    fail(
        "Translation weights are missing from the local cache. Provision "
        "the NLLB model first; see LOCAL_TRANSLATION_SETUP.md. "
        "This launcher will not download it."
    )

kg_paths = [
    Path(path).expanduser().resolve()
    for path in (args.kg or ["data/production_graph/garo_1_kg_refined.csv"])
]
for path in kg_paths:
    if not path.is_file():
        fail(f"KG CSV not found: {path}")

print("Model-file and dependency checks passed; inference is checked at runtime.")
if args.check:
    raise SystemExit(0)

sys.argv = [str(ROOT / "rag.py")]
for path in kg_paths:
    sys.argv.extend(["--kg", str(path)])
sys.argv.extend(["--serve", "--host", "127.0.0.1", "--port", "8000"])
runpy.run_path(str(ROOT / "rag.py"), run_name="__main__")
