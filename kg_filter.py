#!/usr/bin/env python3
"""
kg_filter.py

Post-extraction fact validation for the Garo / Mandi knowledge graph pipeline.
Uses DeepSeek via Ollama's HTTP API (same pattern as scriptdeep1.py) to review
each extracted triple against its source sentence, then drops unsupported /
malformed / off-topic facts.

Tuned for CSVs produced by the extraction script
(columns: extraction_number, paper, subject, predicate, object,
          source_section, confidence, passage, sentence_ref).

Usage:
    python kg_filter.py deepseek-r1_7b_v1.csv
    python kg_filter.py deepseek-r1_7b_v1.csv deepseek-r1:7b
    python kg_filter.py facts.json --model deepseek-r1:14b --out-format json
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
from dataclasses import dataclass, asdict, fields
from pathlib import Path
from typing import Any

import requests


# ============================================================
# 0. Ollama HTTP config (matches scriptdeep1.py)
# ============================================================
OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "deepseek-r1:7b"
REQUEST_TIMEOUT = 150
MAX_RETRIES = 2

# A sentence_ref matching any of these is treated as "no source sentence"
_NO_REFERENCE_VALUES = {"", "no_reference", "none", "null", "n/a", "-"}


# ============================================================
# 1. Data model
# ============================================================

@dataclass
class FactBlock:
    subject: str
    predicate: str
    object_: str
    sentence_ref: str = ""
    source_section: str = ""      # e.g. "Page 5"
    confidence: str = ""          # extractor's string ("High"/"Medium"), preserved
    source: str = ""              # paper stem
    verdict: str = ""             # "KEEP" | "DROP" | "SKIP"
    reason: str = ""

    @property
    def triple(self) -> str:
        return f"({self.subject})-[{self.predicate}]->({self.object_})"

    @property
    def has_sentence(self) -> bool:
        return self.sentence_ref.strip().lower() not in _NO_REFERENCE_VALUES

    def to_comment_block(self) -> str:
        source_line = self.source or "<paper title placeholder>"
        if self.source_section:
            source_line = f"{source_line} ({self.source_section})"
        return (
            f"// PASSAGE: {self.triple}\n"
            f"// SENTENCE REF: {self.sentence_ref}\n"
            f"// SOURCE: {source_line}"
        )


_FIELD_ALIASES: dict[str, set[str]] = {
    "subject":        {"subject", "subj", "s", "head", "entity", "source_entity",
                       "sourceentity", "from", "start"},
    "predicate":      {"predicate", "pred", "p", "relation", "rel", "edge",
                       "relationship", "type", "label"},
    "object_":        {"object", "obj", "o", "tail", "target", "target_entity",
                       "targetentity", "to", "end", "value"},
    # NOTE: "passage" deliberately excluded — in the extractor's CSV, "passage"
    # holds the triple string, not the source sentence.
    "sentence_ref":   {"sentence_ref", "sentenceref", "sentence", "sent",
                       "context", "evidence", "quote", "source_sentence",
                       "sourcesentence", "text"},
    "source_section": {"source_section", "sourcesection", "section", "page",
                       "location", "loc"},
    "confidence":     {"confidence", "conf", "score"},
    "source":         {"source", "paper", "paper_title", "papertitle", "doc",
                       "document", "title", "file"},
}


def _clean_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(k).strip().lower()).strip("_")


def _lookup(record: dict[str, Any], canonical: str) -> Any:
    # 1. exact key match first
    if canonical in record:
        return record[canonical]
    # 2. exact cleaned match
    for k, v in record.items():
        if _clean_key(k) == canonical:
            return v
    # 3. alias match (fallback)
    aliases = _FIELD_ALIASES[canonical]
    for k, v in record.items():
        if _clean_key(k) in aliases:
            return v
    return None


# ============================================================
# 2a. Parser: comment-block text format
# ============================================================

_PASSAGE_LINE_RE = re.compile(r"^//\s*PASSAGE:\s*(?P<s>.*)$")
_SENT_RE         = re.compile(r"^//\s*SENTENCE REF:\s*(?P<s>.*)$")
_SOURCE_RE       = re.compile(r"^//\s*SOURCE:\s*(?P<s>.*)$")
_TRIPLE_RE       = re.compile(
    r"\(\s*(?P<subj>[^)\-]+?)\s*\)\s*-\s*\[\s*:?(?P<pred>[^\]]+?)\s*\]\s*->\s*"
    r"\(\s*(?P<obj>[^)]+?)\s*\)"
)


def parse_comment_blocks(raw: str) -> list[FactBlock]:
    facts: list[FactBlock] = []
    current: dict[str, str] = {}

    def flush() -> None:
        if "passage" not in current:
            return
        m = _TRIPLE_RE.search(current["passage"])
        if m:
            facts.append(FactBlock(
                subject=m.group("subj").strip(),
                predicate=m.group("pred").strip(),
                object_=m.group("obj").strip(),
                sentence_ref=current.get("sentence", "").strip().strip('"'),
                source=current.get("source", "").strip(),
            ))

    for line in raw.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if (m := _PASSAGE_LINE_RE.match(line)):
            flush()
            current = {"passage": m.group("s").strip()}
        elif (m := _SENT_RE.match(line)):
            current["sentence"] = m.group("s").strip()
        elif (m := _SOURCE_RE.match(line)):
            current["source"] = m.group("s").strip()

    flush()
    return facts


# ============================================================
# 2b. Parser: dict / record → FactBlock
# ============================================================

def _record_to_fact(record: dict[str, Any]) -> FactBlock | None:
    # Flatten nested triple dicts like {"triple": {"subject": ...}}
    if isinstance(record.get("triple"), dict):
        record = {**record, **record["triple"]}

    subj = _lookup(record, "subject")
    pred = _lookup(record, "predicate")
    obj  = _lookup(record, "object_")

    # Fallback: scrape a "(A)-[B]->(C)" string anywhere in the record
    if not (subj and pred and obj):
        for v in record.values():
            if isinstance(v, str) and (m := _TRIPLE_RE.search(v)):
                subj, pred, obj = (m.group("subj").strip(),
                                   m.group("pred").strip(),
                                   m.group("obj").strip())
                break

    if not (subj and pred and obj):
        return None

    sent    = _lookup(record, "sentence_ref") or ""
    section = _lookup(record, "source_section") or ""
    conf    = _lookup(record, "confidence") or ""
    source  = _lookup(record, "source") or ""

    return FactBlock(
        subject=str(subj).strip(),
        predicate=str(pred).strip(),
        object_=str(obj).strip(),
        sentence_ref=str(sent).strip().strip('"'),
        source_section=str(section).strip(),
        confidence=str(conf).strip(),
        source=str(source).strip(),
    )


# ============================================================
# 2c. Loaders + format detection
# ============================================================

def _detect_format(path: str, raw: str) -> str:
    if path != "-":
        ext = Path(path).suffix.lower().lstrip(".")
        if ext in {"csv", "json", "jsonl", "ndjson", "txt"}:
            return "jsonl" if ext == "ndjson" else ext

    head = raw.lstrip()[:400]
    if head.startswith("{") and "\n{" in raw[:4000]:
        return "jsonl"
    if head.startswith("[") or head.startswith("{"):
        return "json"
    first = next((ln for ln in raw.splitlines() if ln.strip()), "")
    if first.startswith("//"):
        return "txt"
    if "," in first and ("subject" in first.lower() or "predicate" in first.lower()):
        return "csv"
    return "txt"


def load_facts(path: str) -> list[FactBlock]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    fmt = _detect_format(path, raw)

    if fmt == "txt":
        return parse_comment_blocks(raw)

    if fmt == "csv":
        reader = csv.DictReader(io.StringIO(raw))
        return [f for row in reader if (f := _record_to_fact(row))]

    if fmt == "jsonl":
        out = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and (f := _record_to_fact(obj)):
                out.append(f)
        return out

    obj = json.loads(raw)
    records: list[dict[str, Any]] = []

    if isinstance(obj, list):
        records = [r for r in obj if isinstance(r, dict)]
    elif isinstance(obj, dict):
        for key in ("facts", "triples", "data", "results", "items", "extractions"):
            if isinstance(obj.get(key), list):
                records = [r for r in obj[key] if isinstance(r, dict)]
                break
        else:
            records = [obj]

    return [f for r in records if (f := _record_to_fact(r))]


# ============================================================
# 3. DeepSeek reasoning stripper
# ============================================================

def strip_deepseek_reasoning(raw: str) -> str:
    for marker in ['(', '[', '{']:
        idx = raw.find(marker)
        if idx != -1:
            raw = raw[idx:]
            break
    raw = re.sub(r'^```(?:cypher|json)?\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw)
    return raw.strip()


# ============================================================
# 4. Validator prompts
# ============================================================

SYSTEM_PROMPT = (
    "You are a strict fact-validation assistant for a knowledge graph about the "
    "Garo / Mandi community. You judge whether a candidate triple is a valid, "
    "well-formed, on-topic fact that is genuinely supported by its source sentence."
)

VALIDATOR_TEMPLATE = """{system}

Candidate triple:
  Subject:   {subject}
  Predicate: {predicate}
  Object:    {object_}

Source sentence (the exact sentence this triple claims to come from):
  "{sentence}"

Judge the triple against ALL of the following criteria:

1. SUPPORT — Is the triple genuinely supported by the source sentence?
   Entities and the relationship must be traceable to what the sentence actually
   says. No hallucinated entities. No invented relationships.

2. TOPIC — Is this a fact about the Garo / Mandi community's culture, language,
   history, practices, or lived experience?
   Reject facts about: the research study itself (sample sizes, methods,
   demographics, interview procedures), bibliographic references, citations,
   page numbers, or the researchers' actions.

3. FORM —
   - Subject and Object must be noun phrases (not clauses, not verbs).
   - Predicate must describe a relationship, not restate the sentence.
   - Reject generic placeholder predicates like RELATED_TO, IS, HAS,
     ASSOCIATED_WITH, unless clearly the best fit.
   - Reject empty / single-character / truncated entities, or subject == object.

Respond with ONLY a JSON object, no prose, no markdown fences:
{{"verdict": "KEEP" or "DROP", "reason": "<one short sentence>"}}
"""


# ============================================================
# 5. Ollama HTTP call
# ============================================================

def validate_fact(fact: FactBlock, model: str = DEFAULT_MODEL,
                  retries: int = MAX_RETRIES) -> FactBlock:
    # Fast-path: no source sentence → nothing to validate against. Auto-drop
    # without spending an LLM call.
    if not fact.has_sentence:
        fact.verdict = "DROP"
        fact.reason = "no source sentence (NO_REFERENCE / empty)"
        return fact

    prompt = VALIDATOR_TEMPLATE.format(
        system=SYSTEM_PROMPT,
        subject=fact.subject,
        predicate=fact.predicate,
        object_=fact.object_,
        sentence=fact.sentence_ref,
    )

    last_err = "no response"
    for attempt in range(retries):
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 512},
                },
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                time.sleep(1)
                continue

            raw = resp.json().get("response", "")
            cleaned = strip_deepseek_reasoning(raw)
            fact.verdict, fact.reason = _parse_verdict(cleaned)
            return fact

        except Exception as e:
            last_err = str(e)
            print(f"    attempt {attempt + 1} error: {e}")
            time.sleep(1)

    fact.verdict = "DROP"
    fact.reason = f"validator error: {last_err}"
    return fact


def _parse_verdict(content: str) -> tuple[str, str]:
    content = re.sub(r" thinking.*?", "", content, flags=re.DOTALL)
    content = re.sub(r"```(?:json)?", "", content).replace("```", "").strip()

    try:
        obj = json.loads(content)
        verdict = str(obj.get("verdict", "")).upper().strip()
        reason  = str(obj.get("reason", "")).strip()
        if verdict in ("KEEP", "DROP"):
            return verdict, reason
    except json.JSONDecodeError:
        pass

    upper = content.upper()
    if "KEEP" in upper and "DROP" not in upper:
        return "KEEP", content[:200]
    if "DROP" in upper:
        return "DROP", content[:200]
    return "DROP", f"unparseable verdict: {content[:120]}"


# ============================================================
# 6. Orchestration
# ============================================================

def filter_extraction(
    facts: list[FactBlock],
    model: str = DEFAULT_MODEL,
    verbose: bool = True,
) -> tuple[list[FactBlock], list[FactBlock]]:
    kept: list[FactBlock] = []
    dropped: list[FactBlock] = []

    # Count facts that will skip the LLM call, so we don't print scary progress
    total = len(facts)
    skipped_ahead = sum(1 for f in facts if not f.has_sentence)
    llm_calls = total - skipped_ahead

    if verbose and skipped_ahead:
        print(f"({skipped_ahead} facts have no source sentence — auto-dropped, "
              f"no LLM call)")
        print(f"({llm_calls} facts will be sent to {model})\n")

    for i, fact in enumerate(facts, 1):
        validate_fact(fact, model=model)

        mark = "✓" if fact.verdict == "KEEP" else "✗"
        if verbose:
            print(f"[{i}/{total}] {mark} {fact.triple}  — {fact.reason}")

        (kept if fact.verdict == "KEEP" else dropped).append(fact)

    return kept, dropped


# ============================================================
# 7. Output writers
# ============================================================

# Match the extractor's column layout exactly, plus verdict + reason.
_CSV_FIELDS = [
    "extraction_number", "paper", "subject", "predicate", "object",
    "source_section", "confidence", "passage", "sentence_ref",
    "verdict", "reason",
]


def write_facts(facts: list[FactBlock], path: Path, fmt: str) -> None:
    fmt = fmt.lower()

    if fmt == "txt":
        path.write_text(
            "\n\n".join(f.to_comment_block() for f in facts),
            encoding="utf-8",
        )

    elif fmt == "csv":
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
            writer.writeheader()
            for i, f in enumerate(facts, 1):
                writer.writerow({
                    "extraction_number": i,
                    "paper": f.source,
                    "subject": f.subject,
                    "predicate": f.predicate,
                    "object": f.object_,
                    "source_section": f.source_section,
                    "confidence": f.confidence,
                    "passage": f"({f.subject})-[:{f.predicate}]->({f.object_})",
                    "sentence_ref": f.sentence_ref,
                    "verdict": f.verdict,
                    "reason": f.reason,
                })

    elif fmt == "jsonl":
        with path.open("w", encoding="utf-8") as fh:
            for i, f in enumerate(facts, 1):
                rec = asdict(f)
                rec["extraction_number"] = i
                fh.write(json.dumps(rec) + "\n")

    elif fmt == "json":
        data = []
        for i, f in enumerate(facts, 1):
            rec = asdict(f)
            rec["extraction_number"] = i
            data.append(rec)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    else:
        raise ValueError(f"unknown output format: {fmt!r}")


# ============================================================
# 8. CLI
# ============================================================

def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python kg_filter.py <facts.(txt|csv|json|jsonl)|-> "
              "[model] [--model NAME] [--out-format txt|csv|json|jsonl]")
        return 1

    path = sys.argv[1]
    model = DEFAULT_MODEL
    out_fmt = "csv"    # default to CSV to match the extractor's format

    if len(sys.argv) > 2 and not sys.argv[2].startswith("--"):
        model = sys.argv[2]
    if "--model" in sys.argv:
        model = sys.argv[sys.argv.index("--model") + 1]
    if "--out-format" in sys.argv:
        out_fmt = sys.argv[sys.argv.index("--out-format") + 1].lower()

    try:
        facts = load_facts(path)
    except Exception as e:
        print(f"failed to load facts from {path!r}: {e}", file=sys.stderr)
        return 2

    if not facts:
        print("no facts parsed — check the input file's format.", file=sys.stderr)
        return 3

    print(f"loaded {len(facts)} facts from {path} (format auto-detected)")
    print(f"using model: {model}")

    missing = sum(1 for f in facts if not f.has_sentence)
    if missing == len(facts):
        print("⚠️  WARNING: all facts have empty sentence_ref — the parser may be "
              "reading the wrong column. Check your CSV headers.")
    elif missing:
        print(f"note: {missing}/{len(facts)} facts have no usable sentence_ref")
    print()

    kept, dropped = filter_extraction(facts, model=model)

    print("\n" + "=" * 60)
    print(f"kept {len(kept)} / dropped {len(dropped)} "
          f"(total {len(kept) + len(dropped)})")
    print("=" * 60)

    write_facts(kept, Path(f"facts_kept.{out_fmt}"), out_fmt)
    write_facts(dropped, Path(f"facts_dropped.{out_fmt}"), out_fmt)
    print(f"wrote facts_kept.{out_fmt} and facts_dropped.{out_fmt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())