"""Optional sentence translation using a predownloaded NLLB research model.

Runtime loading is offline. One lock protects mutable tokenizer language state.
"""
import os
import re
import threading

_LOCK = threading.RLock()
_ENGINE = None
_LANGUAGES = {"en": "eng_Latn", "bn": "ben_Beng", "hi": "hin_Deva"}



# Explicit community-name forms only; do not replace substrings inside words.
_BANGLA_NAMES = {
    "গারোরা": "Garo জনগণ", "গারোদের": "Garo জনগণের", "গারো": "Garo",
    "মান্দিরা": "Mandi জনগণ", "মান্দিদের": "Mandi জনগণের", "মান্দি": "Mandi",
}
# A sentence end, except after a single-letter abbreviation. The obvious
# pattern, r"(?<=[.!?।])\s+", splits "the seeds of T. indica and
# S. cumini" into three fragments, and the Bangla came back as "the seeds
# of T. are used. Indica and S. Cumini in their formulations" -- measured
# 2026-10-28 against NLLB, recorded in KNOWN_LIMITATIONS 29. Species
# abbreviations are ordinary in this corpus, so the splitter has to know
# about them.
_SENTENCE_SPLIT = re.compile(r"(?<!\b[A-Z]\.)(?<=[.!?।])\s+")


_NAME_PATTERN = re.compile(r"(?<!\w)(" + "|".join(_BANGLA_NAMES) + r")(?!\w)")


def _prepare_names(text, source, target):
    if source == "bn" and target == "en":
        return _NAME_PATTERN.sub(lambda match: _BANGLA_NAMES[match[0]], text)
    return text


def _names_preserved(source_text, result, target):
    if target != "en":
        return True
    for name in ("Garo", "Mandi"):
        pattern = r"\b" + name + r"\b"
        expected = len(re.findall(pattern, source_text, re.IGNORECASE))
        if len(re.findall(pattern, result, re.IGNORECASE)) < expected:
            return False
    return True


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
        for sentence in re.split(_SENTENCE_SPLIT, paragraph.strip()):
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
            prepared = _prepare_names(text, source, target)
            for chunk in _chunks(prepared, tokenizer):
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
                        max_new_tokens=512, do_sample=False, num_beams=5,
                    )
                tokens = output[0].tolist()
                # A length-limited result must not silently drop the rest.
                if not tokens or tokens[-1] != model.config.eos_token_id:
                    return ""
                result = tokenizer.decode(output[0], skip_special_tokens=True).strip()
                if not result or not _names_preserved(chunk, result, target):
                    return ""
                current.append(result)
            if current:
                paragraphs.append(" ".join(current))
            return "\n".join(paragraphs)
    except Exception as error:
        # Avoid logging source text or exception messages containing private text.
        print(f"Local translation unavailable ({type(error).__name__}); check cached model and dependencies.")
        return ""
