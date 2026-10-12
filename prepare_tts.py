"""Download a public speech model, or generate an offline pronunciation sample."""
import argparse
import os
from pathlib import Path
from local_tts import MODELS, LocalMmsEngine, validate_payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--language', choices=list(MODELS), default='bn')
    parser.add_argument('--sample', help='Generate this text using a downloaded model; no network.')
    parser.add_argument('--output', default='tts-sample.wav')
    args = parser.parse_args()
    if args.sample:
        text, language = validate_payload({'text': args.sample, 'language': args.language})
        Path(args.output).write_bytes(LocalMmsEngine().render(text, language))
        print(f'Created {args.output}. Have a fluent speaker check pronunciation.')
    else:
        from transformers import AutoTokenizer, VitsModel
        folder = Path(os.getenv('TTS_MODEL_DIR', 'models/tts')) / args.language
        folder.mkdir(parents=True, exist_ok=True)
        AutoTokenizer.from_pretrained(MODELS[args.language]).save_pretrained(folder)
        VitsModel.from_pretrained(MODELS[args.language]).save_pretrained(folder)
        print(f'Downloaded {MODELS[args.language]} into {folder}. Inference uses local files only.')


if __name__ == '__main__':
    main()
