"""Optional sentence translation using a predownloaded NLLB research model.

Runtime loading is offline. One lock protects mutable tokenizer language state.
"""
import os
import re
import threading

_LOCK = threading.RLock()
_ENGINE = None
_LANGUAGES = {"en": "eng_Latn", "bn": "ben_Beng", "hi": "hin_Deva"}


def _load_engine():
    global _ENGINE
    if _ENGINE is None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        location = os.getenv("LOCAL_TRANSLATION_MODEL", "facebook/nllb-200-distilled-600M")
        tokenizer = AutoTokenizer.from_pretrained(location, src_lang="eng_Latn", local_files_only=True)
        model = AutoModelForSeq2SeqLM.from_pretrained(
            location, local_files_only=True, use_safetensors=False,
        )
        model.eval()
        _ENGINE = (tokenizer, model, torch)
    return _ENGINE


def _chunks(text, tokenizer, limit=384):
    # Retain paragraph boundaries; split sentences before token-aware subdivision.
    for paragraph in text.splitlines():
        if not paragraph.strip():
            yield None
            continue
        for sentence in re.split(r"(?<=[.!?।])\s+", paragraph.strip()):
            pending = sentence
            while pending:
                if len(tokenizer.encode(pending, add_special_tokens=True)) <= limit:
                    yield pending
                    break
                lo, hi = 1, len(pending)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if len(tokenizer.encode(pending[:mid], add_special_tokens=True)) <= limit:
                        lo = mid
                    else:
                        hi = mid - 1
                end = pending.rfind(" ", 0, lo + 1)
                if end < lo // 2:
                    end = lo
                yield pending[:end].strip()
                pending = pending[end:].lstrip()


def translate_local(text, source, target):
    """Return translated text, or empty on failure; never use an online fallback."""
    if source not in _LANGUAGES or target not in _LANGUAGES:
        raise ValueError("Unsupported local translation language")
    if source == target or not text.strip():
        return text
    try:
        with _LOCK:
            tokenizer, model, torch = _load_engine()
            tokenizer.src_lang = _LANGUAGES[source]
            target_id = tokenizer.convert_tokens_to_ids(_LANGUAGES[target])
            paragraphs, current = [], []
            for chunk in _chunks(text, tokenizer):
                if chunk is None:
                    if current:
                        paragraphs.append(" ".join(current))
                        current = []
                    paragraphs.append("")
                    continue
                inputs = tokenizer(chunk, return_tensors="pt", truncation=False)
                with torch.inference_mode():
                    output = model.generate(
                        **inputs, forced_bos_token_id=target_id,
                        max_new_tokens=512, do_sample=False,
                    )
                tokens = output[0].tolist()
                # A length-limited result must not silently drop the rest.
                if not tokens or tokens[-1] != model.config.eos_token_id:
                    return ""
                result = tokenizer.decode(output[0], skip_special_tokens=True).strip()
                if not result:
                    return ""
                current.append(result)
            if current:
                paragraphs.append(" ".join(current))
            return "\n".join(paragraphs)
    except Exception as error:
        # Avoid logging source text or exception messages containing private text.
        print(f"Local translation unavailable ({type(error).__name__}); check cached model and dependencies.")
        return ""
