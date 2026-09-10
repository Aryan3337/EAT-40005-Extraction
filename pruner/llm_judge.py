"""
Tier 3 -- LLM-as-judge semantic check.

For each new relationship, asks an LLM whether the triple belongs in this
knowledge graph, and gets back a confidence score in [0, 1].

  score <  LLM_JUDGE_LOW_THRESHOLD   -> auto-delete as noise
  score >= LLM_JUDGE_HIGH_THRESHOLD  -> keep, tag with the score
  in between                        -> flag for human review

--- Verified against the actual pipeline on 2026-09-09 ---
The original JUDGE_PROMPT only asked "is this stated or implied by the
source text" -- pure hallucination detection. Checked against the 27
methodology-leak triples actually found in this project's garo_1.pdf run
(things like `(Respondents)-[KNOWN_ORIGIN]->(Tibet)` or
`(GaroCommunity)-[SAMPLE]->(Purposive sampling)`), that question doesn't
catch them: the source sentences genuinely do say what the triple claims
-- the extraction was faithful, just off-topic (describing the research
process/respondent demographics rather than the community itself). A
faithfulness-only judge would score these HIGH confidence and keep them.
JUDGE_PROMPT below now asks both questions -- textual support AND
whether the triple is actually a fact about the Garo/Mandi community
(mirroring the skip-list already used at extraction time in
kg_extractor.py's make_extraction_prompt) -- and returns low confidence
if either fails.

This is deliberately pluggable: `judge_triple()`-style backends take any
callable with signature (subject, relation, obj, source_text) -> (float,
str). Three example backends are provided below (OpenAI, Anthropic, and a
local Ollama call). Set LLM_JUDGE_BACKEND accordingly, or pass a custom
function into run_tier3(..., judge_fn=my_function).
"""

import json
import os
import re

from . import audit, config, rules

LLM_JUDGE_BACKEND = os.environ.get("LLM_JUDGE_BACKEND", "none")

# Ollama endpoint for the judge. Matches the convention the main pipeline
# already uses (kg_extractor.py's OLLAMA_URL): "localhost" only resolves
# correctly if this runs directly on the host machine (where
# docker-compose.yml's "11434:11434" port mapping makes it reachable). If
# you run this from inside the `app` container instead (e.g. via
# `docker compose exec app python run_prune.py ...`), set
# OLLAMA_JUDGE_URL=http://ollama:11434/api/generate to use the Docker
# service name, same as the main pipeline's .env does for OLLAMA_URL.
OLLAMA_JUDGE_URL = os.environ.get("OLLAMA_JUDGE_URL", "http://localhost:11434/api/generate")

JUDGE_PROMPT = """You are checking one entry in a knowledge graph about the Garo / Mandi community for whether it belongs.

Source text:
\"\"\"{source_text}\"\"\"

Extracted triple: ({subject}) -[{relation}]-> ({obj})

Answer two questions about this triple, then give one combined confidence score:

1. Is this relationship actually stated or clearly implied by the source text? (textual support)
2. Is this a genuine fact about the Garo/Mandi community's culture, language, history, beliefs, practices, or lived experience -- NOT a description of the research process itself (sample sizes, participant/respondent counts or demographics, what respondents were asked/told/observed to say, interview or data collection methods, research objectives, or any other statement about what "the study" or "the researchers" did)? (topical relevance)

If either answer is no, the triple does not belong in this graph, even if the other answer is yes -- a triple can be perfectly faithful to the source text and still be noise if the source text itself was describing the study rather than the community (e.g. "(Respondents)-[KNOWN_ORIGIN]->(Tibet)" is textually supported by a sentence about what respondents said, but fails question 2).

Respond with ONLY a JSON object: {{"confidence": <float 0.0-1.0>, "reason": "<one short sentence>"}}
1.0 means both questions are clearly yes. 0.0 means either question is clearly no (hallucinated, or a methodology/research-process description rather than a community fact)."""


def _parse_response(text: str):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return 0.5, "unparseable_judge_response"
    try:
        data = json.loads(match.group(0))
        return float(data.get("confidence", 0.5)), data.get("reason", "")
    except (ValueError, json.JSONDecodeError):
        return 0.5, "unparseable_judge_response"


def judge_with_openai(subject, relation, obj, source_text, model="gpt-4o-mini"):
    from openai import OpenAI

    client = OpenAI()
    prompt = JUDGE_PROMPT.format(source_text=source_text, subject=subject, relation=relation, obj=obj)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return _parse_response(resp.choices[0].message.content)


def judge_with_anthropic(subject, relation, obj, source_text, model="claude-haiku-4-5"):
    import anthropic

    client = anthropic.Anthropic()
    prompt = JUDGE_PROMPT.format(source_text=source_text, subject=subject, relation=relation, obj=obj)
    resp = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_response(resp.content[0].text)


def judge_with_ollama(subject, relation, obj, source_text, model="deepseek-r1:7b"):
    """For a local model served by Ollama -- defaults to deepseek-r1:7b to
    match the model the main extraction pipeline already uses (see
    kg_extractor.py / main.py), so no second model needs to be pulled.
    Requires `pip install requests` and a running `ollama serve`. Endpoint
    is OLLAMA_JUDGE_URL (see module docstring for container vs. host
    caveat)."""
    import requests

    prompt = JUDGE_PROMPT.format(source_text=source_text, subject=subject, relation=relation, obj=obj)
    resp = requests.post(
        OLLAMA_JUDGE_URL,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=60,
    )
    resp.raise_for_status()
    return _parse_response(resp.json().get("response", ""))


_BACKENDS = {
    "openai": judge_with_openai,
    "anthropic": judge_with_anthropic,
    "ollama": judge_with_ollama,
}


def get_default_judge_fn():
    if LLM_JUDGE_BACKEND == "none":
        return None
    fn = _BACKENDS.get(LLM_JUDGE_BACKEND)
    if fn is None:
        raise ValueError(f"Unknown LLM_JUDGE_BACKEND: {LLM_JUDGE_BACKEND}")
    return fn


def _fetch_source_text(conn, rel_props, node_props_pair):
    """Resolves the passage of text a triple should be checked against.
    In "property" mode the text is stored directly; in "lookup" mode you
    need to supply your own document store lookup here."""
    if config.SOURCE_TEXT_MODE == "property":
        return rel_props.get(config.SOURCE_TEXT_PROPERTY) or next(
            (p.get(config.SOURCE_TEXT_PROPERTY) for p in node_props_pair if p.get(config.SOURCE_TEXT_PROPERTY)),
            None,
        )
    # "lookup" mode: replace this with a real fetch against your document
    # store, keyed by rel_props[config.SOURCE_PROPERTY] (a doc/interview ID).
    return None


def _fetch_batch_relationships(conn, batch_id):
    where_batch = f"AND r.{config.BATCH_PROPERTY} = $batch_id" if batch_id is not None else ""
    cypher = f"""
    MATCH (a)-[r]->(b)
    WHERE NOT coalesce(r.{config.REVIEW_FLAG_PROPERTY}, false)
    {where_batch}
    RETURN elementId(r) AS id, type(r) AS type, properties(r) AS rel_props,
           properties(a) AS a_props, properties(b) AS b_props,
           a.name AS a_name, b.name AS b_name
    """
    return conn.run(cypher, batch_id=batch_id)


def run_tier3(conn, batch_id=None, dry_run=False, judge_fn=None):
    """Runs the LLM judge over every relationship in the batch that still
    has a resolvable source text. Skips (leaves untouched) anything it
    can't find text for -- Tier 1 already removed triples with no source
    reference at all."""
    judge_fn = judge_fn or get_default_judge_fn()
    summary = {"deleted": 0, "flagged": 0, "kept": 0, "skipped_no_text": 0}

    if judge_fn is None:
        summary["skipped_no_judge_configured"] = True
        return summary

    for row in _fetch_batch_relationships(conn, batch_id):
        source_text = _fetch_source_text(conn, row["rel_props"], [row["a_props"], row["b_props"]])
        if not source_text:
            summary["skipped_no_text"] += 1
            continue

        confidence, reason = judge_fn(row["a_name"], row["type"], row["b_name"], source_text)

        if confidence < config.LLM_JUDGE_LOW_THRESHOLD:
            rules.delete_relationship(
                conn, row["id"], f"llm_judge_unsupported:{reason}", batch_id, dry_run
            )
            summary["deleted"] += 1
        elif confidence < config.LLM_JUDGE_HIGH_THRESHOLD:
            rules.flag_relationship(
                conn, row["id"], f"llm_judge_uncertain:{reason}", dry_run,
                extra_props={config.CONFIDENCE_PROPERTY: confidence},
            )
            summary["flagged"] += 1
        else:
            if not dry_run:
                conn.run(
                    f"""
                    MATCH ()-[r]->() WHERE elementId(r) = $id
                    SET r.{config.CONFIDENCE_PROPERTY} = $confidence
                    """,
                    id=row["id"], confidence=confidence,
                )
            summary["kept"] += 1

    return summary
