# Synthesis Relevance Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the chatbot fabricating connections between unrelated facts by making the model declare, on its first line, whether the evidence actually answers the question — and discarding everything after a "no" in code rather than trusting the model to stop writing.

**Architecture:** One new instruction at the top of the synthesis prompt asks for a `RELEVANT: yes` / `RELEVANT: no` first line. A new pure parser reads that marker off the model's cleaned output and returns the prose only on `yes`, returning `None` on `no`, on a missing marker, or on a malformed one (fail closed). `answer()` turns a `None` into a fixed honest refusal message and deliberately does **not** route it into `_fallback_answer`, whose templated triple soup is the exact padding being removed. A `SYNTHESIS_RELEVANCE_GATE` env var defaulting to on turns the whole thing off for demo rollback without a code change. Call count is unchanged at one Ollama call per question.

**Tech Stack:** Python 3.14, `requests`, `pytest` (with `monkeypatch`), existing local Ollama via `llm_endpoint.resolve_llm_endpoint`.

**Spec:** `docs/superpowers/specs/2026-10-08-synthesis-relevance-gate-design.md`

## Global Constraints

- **Local inference only.** No third-party model provider, ever. All calls go through the existing `resolve_llm_endpoint`-guarded local Ollama. (Spec §1.4)
- **No additional LLM round-trips.** Exactly one Ollama call per question, as today. 2 of 3 real hosted requests failed with `SSLEOFError` on 2026-10-08; each extra call is another independent chance of total failure. (Spec §1.4)
- **Fail closed.** Any response the parser cannot confidently read as `yes` is a refusal. Never return unvalidated prose. (Spec §1.3, §2.2)
- **Reversible without a code change.** `SYNTHESIS_RELEVANCE_GATE` defaults to on; setting it falsey restores exactly today's behaviour. (Spec §2.4)
- **Do not modify** retrieval ranking, the graph, the Flutter client, or the `_fallback_answer` template path. (Spec §1.5)
- All work on branch `marcus-extraction-gates`. Full suite must stay green: `py -3.14 -m pytest -q` (299 tests passing as of `540257c`).

## File Structure

- `rag.py` — all production changes. Three regions: the synthesis constants block (~lines 801-849), `AnswerSynthesizer.answer()` (~lines 888-926), `AnswerSynthesizer._build_prompt()` (~lines 928-966). New method `_parse_gated_response()` goes directly after `_clean_response()` (~line 972), since it consumes it.
- `tests/test_answer_synthesis.py` — all new tests. Existing file already covers `answer()`'s timeout/model/cache behaviour and establishes the stubbing pattern (`monkeypatch.setattr("rag.requests.post", fake_post)`, `answer_cache={}` to bypass the real demo cache).
- `KNOWN_LIMITATIONS.md` — updated in Task 4 only, after live verification decides whether this ships.

---

### Task 1: The response parser

**Files:**
- Modify: `rag.py` (add `_parse_gated_response` immediately after `_clean_response`, ~line 972)
- Test: `tests/test_answer_synthesis.py`

**Interfaces:**
- Consumes: `AnswerSynthesizer._clean_response(text: str) -> str` (existing, line 969).
- Produces: `AnswerSynthesizer._parse_gated_response(self, text: str) -> Optional[str]` — returns the answer prose on `yes`, `None` on refusal/missing/malformed. Task 3 calls this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_answer_synthesis.py`:

```python
# -- the relevance gate's parser ---------------------------------------------
#
# WHY THIS EXISTS: measured live 2026-10-08, synthesis fabricated a citation
# ("as stated in Putz (1991) who identified family as one of the domains of
# study") linking two facts that share only the keyword "family". The model's
# own answer OPENED with "The evidence provided does not directly answer..."
# and then kept writing anyway -- its judgement was never the broken part, the
# unconstrained continuation was. So the parser's job is to discard everything
# after a "no" in code. Two prior prompt-only fixes that asked the model to
# restrain itself were both reverted after failing live retests.


def _synthesizer():
    return AnswerSynthesizer(
        ollama_url="http://localhost:11434/api/generate", answer_cache={}
    )


def test_a_yes_marker_returns_the_prose_below_it():
    result = _synthesizer()._parse_gated_response(
        "RELEVANT: yes\nThe Garo community speaks Garo and Mandi."
    )
    assert result == "The Garo community speaks Garo and Mandi."


def test_a_no_marker_discards_everything_the_model_wrote_after_it():
    # The exact 2026-10-08 failure shape: an honest opener followed by
    # fabricated bridging prose. The prose must not survive.
    result = _synthesizer()._parse_gated_response(
        "RELEVANT: no\nHowever, it is mentioned that traditional practices "
        "are being modified in response to modernization, as stated in "
        "Putz (1991)."
    )
    assert result is None


def test_a_missing_marker_fails_closed():
    result = _synthesizer()._parse_gated_response(
        "The Garo community resides primarily in the Garo Hills."
    )
    assert result is None


def test_an_unrecognised_marker_value_fails_closed():
    # "nope" must not be read as a prefix of "no" -- nor as a yes.
    assert _synthesizer()._parse_gated_response("RELEVANT: nope\nSomething.") is None
    assert _synthesizer()._parse_gated_response("RELEVANT: maybe\nSomething.") is None


def test_a_thinking_model_preamble_is_stripped_before_the_marker_is_read():
    # deepseek-r1:7b emits <think>...</think> before anything else. Without
    # _clean_response running first, the marker is never on the first line
    # and every answer would fail closed.
    result = _synthesizer()._parse_gated_response(
        "<think>The user asks about language. The evidence covers it.</think>\n"
        "RELEVANT: yes\nThe Garo community speaks Garo."
    )
    assert result == "The Garo community speaks Garo."


def test_the_marker_is_case_and_whitespace_insensitive():
    result = _synthesizer()._parse_gated_response(
        "  relevant:YES  \n\nThe Garo community speaks Garo."
    )
    assert result == "The Garo community speaks Garo."


def test_a_yes_marker_with_no_answer_body_fails_closed():
    assert _synthesizer()._parse_gated_response("RELEVANT: yes\n   \n") is None


def test_a_yes_marker_sharing_its_line_with_the_answer_still_returns_it():
    # Robustness against format drift: if the model puts the marker and the
    # answer on one line, dropping the answer would cause a false refusal --
    # the over-refusal risk called out in the spec's risks section.
    result = _synthesizer()._parse_gated_response(
        "RELEVANT: yes The Garo community speaks Garo."
    )
    assert result == "The Garo community speaks Garo."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `py -3.14 -m pytest tests/test_answer_synthesis.py -k gated -v`
Expected: FAIL — `AttributeError: 'AnswerSynthesizer' object has no attribute '_parse_gated_response'`

- [ ] **Step 3: Write the implementation**

In `rag.py`, directly after `_clean_response` (which ends at line 972 with `return text.strip()`):

```python
    # Reads the RELEVANT: yes/no marker the gate instruction asks for, and
    # returns the answer ONLY when the model vouched for its evidence.
    #
    # Returns None for a refusal -- including when the marker is missing or
    # unreadable. An unparseable response is not evidence that the answer is
    # grounded, and this project prefers an honest refusal to a confident
    # wrong one. See docs/superpowers/specs/2026-10-08-synthesis-relevance-gate-design.md
    #
    # _clean_response runs FIRST, and that order is load-bearing: deepseek-r1
    # emits <think>...</think> before anything else, and _clean_response also
    # strips a leading "Answer:" prefix, so "Answer: RELEVANT: yes" still
    # leaves the marker on line one.
    def _parse_gated_response(self, text: str) -> Optional[str]:
        cleaned = self._clean_response(text)
        lines = [line for line in cleaned.splitlines() if line.strip()]
        if not lines:
            return None

        match = re.match(r"\s*RELEVANT\s*:\s*(yes|no)\b[.:]?\s*", lines[0], flags=re.IGNORECASE)
        if not match or match.group(1).lower() == "no":
            return None

        # Keep anything trailing the marker on its own line: a model that
        # writes "RELEVANT: yes The Garo..." has still answered, and dropping
        # it would be a false refusal.
        head = lines[0][match.end():].strip()
        tail = "\n".join(lines[1:]).strip()
        remainder = "\n".join(part for part in (head, tail) if part).strip()
        return remainder or None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `py -3.14 -m pytest tests/test_answer_synthesis.py -k gated -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full suite**

Run: `py -3.14 -m pytest -q`
Expected: 307 passed (299 existing + 8 new)

- [ ] **Step 6: Commit**

```bash
git add rag.py tests/test_answer_synthesis.py
git commit -m "Add the relevance gate's response parser

Reads a RELEVANT: yes/no first line off the model's cleaned output and
returns prose only on yes. Fails closed on a missing or unreadable
marker: an unparseable response is not evidence that an answer is
grounded.

Not wired into answer() yet.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The kill switch and the prompt instruction

**Files:**
- Modify: `rag.py` (constants block after `ANSWER_SYNTHESIS_CONNECTION_RETRIES`, ~line 838; `_build_prompt`, ~lines 928-966)
- Test: `tests/test_answer_synthesis.py`

**Interfaces:**
- Produces: module-level `relevance_gate_enabled() -> bool` and `_FALSEY: set[str]`. Task 3 calls `relevance_gate_enabled()`.
- Produces: `_build_prompt` output now contains the gate instruction when enabled.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_answer_synthesis.py`:

```python
def test_the_gate_is_on_by_default(monkeypatch):
    # Default ON is the whole point -- an unset variable must not silently
    # disable the fix. Note the default passed to os.getenv is "on", NOT ""
    # ("" is in _FALSEY and would invert this).
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    assert relevance_gate_enabled() is True


def test_the_gate_can_be_switched_off_for_demo_rollback(monkeypatch):
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("SYNTHESIS_RELEVANCE_GATE", value)
        assert relevance_gate_enabled() is False, value


def test_the_prompt_carries_the_gate_instruction_when_enabled(monkeypatch):
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    prompt = _synthesizer()._build_prompt("What language do they speak?", [_triple()])
    assert "RELEVANT: yes" in prompt
    assert "RELEVANT: no" in prompt


def test_the_prompt_omits_the_gate_instruction_when_switched_off(monkeypatch):
    monkeypatch.setenv("SYNTHESIS_RELEVANCE_GATE", "0")
    prompt = _synthesizer()._build_prompt("What language do they speak?", [_triple()])
    assert "RELEVANT:" not in prompt
```

Add the new name to the imports at the top of the test file:

```python
from rag import (
    ANSWER_SYNTHESIS_CONNECT_TIMEOUT_SECONDS,
    ANSWER_SYNTHESIS_CONNECTION_RETRIES,
    ANSWER_SYNTHESIS_TIMEOUT_SECONDS,
    SYNTHESIS_EVIDENCE_LIMIT,
    AnswerSynthesizer,
    load_demo_answer_cache,
    relevance_gate_enabled,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `py -3.14 -m pytest tests/test_answer_synthesis.py -k "gate" -v`
Expected: FAIL — `ImportError: cannot import name 'relevance_gate_enabled' from 'rag'`

- [ ] **Step 3: Add the kill switch**

In `rag.py`, after `ANSWER_SYNTHESIS_CONNECTION_RETRIES = 1` (line 838):

```python
# Same spelling of "off" as llm_endpoint.py's ALLOW_EXTERNAL_LLM check,
# rather than a second convention in the same codebase. Defined here rather
# than imported because llm_endpoint._FALSEY is private to that module.
_FALSEY = {"", "0", "false", "no", "off"}


# The relevance gate makes the model declare on its first line whether the
# evidence actually answers the question, and rag.py discards everything
# after a "no" instead of trusting the model to stop writing (see
# _parse_gated_response). Defaults ON.
#
# SYNTHESIS_RELEVANCE_GATE=0 restores pre-2026-10-08 behaviour without a code
# change -- a rollback switch for the 2026-10-09 demo, settable from the
# Render dashboard. NOTE the "on" default below: os.getenv's fallback must
# not be "", which is itself in _FALSEY and would invert the default.
def relevance_gate_enabled() -> bool:
    return os.getenv("SYNTHESIS_RELEVANCE_GATE", "on").strip().lower() not in _FALSEY
```

- [ ] **Step 4: Add the instruction to the prompt**

In `_build_prompt`, after the `evidence` list is built (after line 938) and before the `return f"""...`:

```python
        # Asking for a bounded first-line verdict, then enforcing the
        # consequence in code, is the part that differs from the two
        # prompt-only attempts reverted on 2026-10-07 -- both asked the model
        # to self-regulate its prose and it simply did not.
        gate_instruction = """Before answering, judge whether the evidence below directly answers the question.
Your FIRST line must be exactly one of:
RELEVANT: yes
RELEVANT: no
Write "no" if the evidence only touches the topic indirectly, mentions a
related word, or would require you to infer a connection the evidence does
not itself state. If "no", write nothing after that line.
If "yes", write the answer below it, using only evidence that directly
supports it.

""" if relevance_gate_enabled() else ""
```

Then insert `{gate_instruction}` into the returned f-string, immediately before `User question:` — i.e. change these lines:

```python
    add a closing disclaimer out of habit.

User question:
```

to:

```python
    add a closing disclaimer out of habit.

{gate_instruction}User question:
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `py -3.14 -m pytest tests/test_answer_synthesis.py -k "gate" -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `py -3.14 -m pytest -q`
Expected: 311 passed

- [ ] **Step 7: Commit**

```bash
git add rag.py tests/test_answer_synthesis.py
git commit -m "Add the relevance gate instruction and its kill switch

The prompt now asks for a RELEVANT: yes/no first line.
SYNTHESIS_RELEVANCE_GATE defaults on and restores the previous behaviour
when set falsey, so the demo can be rolled back from the Render dashboard
without a code change.

Still not wired into answer() -- the marker is requested but not yet acted on.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Wire the gate into `answer()`

**Files:**
- Modify: `rag.py` (constants ~line 849; `answer()` lines 888-926)
- Test: `tests/test_answer_synthesis.py`

**Interfaces:**
- Consumes: `_parse_gated_response` (Task 1), `relevance_gate_enabled` (Task 2).
- Produces: module-level `NO_GROUNDED_ANSWER_MESSAGE: str`; `answer()` returns it on a gated refusal.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_answer_synthesis.py`:

```python
def _fake_ollama(text):
    """Stubs a successful Ollama call returning `text` as the model output."""

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"response": text}

    def fake_post(url, json, timeout, headers=None):
        return _Response()

    return fake_post


def test_a_gated_refusal_returns_the_honest_message(monkeypatch):
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    monkeypatch.setattr(
        "rag.requests.post",
        _fake_ollama("RELEVANT: no\nHowever, traditional practices are being modified."),
    )
    result = _synthesizer().answer("How do the Garo trace inheritance?", [_triple()])
    assert result == NO_GROUNDED_ANSWER_MESSAGE


def test_a_gated_refusal_does_not_fall_back_to_the_triple_templates(monkeypatch):
    # _fallback_answer renders "Based on the available knowledge, ..." from
    # the triples -- the exact off-topic padding this gate exists to remove.
    # A refusal must not route into it.
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    monkeypatch.setattr("rag.requests.post", _fake_ollama("RELEVANT: no\nSomething."))
    result = _synthesizer().answer("How do the Garo trace inheritance?", [_triple()])
    assert "Based on the available knowledge" not in result
    assert "bilingual" not in result.lower()


def test_a_gated_pass_returns_the_models_prose(monkeypatch):
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    monkeypatch.setattr(
        "rag.requests.post",
        _fake_ollama("RELEVANT: yes\nThe Garo people are bilingual in Bengali."),
    )
    result = _synthesizer().answer("What languages do they speak?", [_triple()])
    assert result == "The Garo people are bilingual in Bengali."


def test_an_unmarked_response_fails_closed_rather_than_passing_prose_through(monkeypatch):
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)
    monkeypatch.setattr("rag.requests.post", _fake_ollama("The Garo people are bilingual."))
    result = _synthesizer().answer("What languages do they speak?", [_triple()])
    assert result == NO_GROUNDED_ANSWER_MESSAGE


def test_with_the_gate_off_prose_is_returned_unmodified(monkeypatch):
    # The rollback path must behave exactly as before: no marker expected,
    # no parsing, model output returned as-is.
    monkeypatch.setenv("SYNTHESIS_RELEVANCE_GATE", "0")
    monkeypatch.setattr("rag.requests.post", _fake_ollama("The Garo people are bilingual."))
    result = _synthesizer().answer("What languages do they speak?", [_triple()])
    assert result == "The Garo people are bilingual."


def test_a_cached_answer_is_never_run_through_the_gate(monkeypatch):
    # Cached demo answers contain no RELEVANT marker, so if the gate were
    # ever applied before the cache short-circuit, all three scripted demo
    # questions would fail closed and refuse on stage. Locks the ordering.
    monkeypatch.delenv("SYNTHESIS_RELEVANCE_GATE", raising=False)

    def explode(*args, **kwargs):
        raise AssertionError("a cached answer must not reach Ollama")

    monkeypatch.setattr("rag.requests.post", explode)
    synthesizer = AnswerSynthesizer(
        ollama_url="http://localhost:11434/api/generate",
        answer_cache={"where do the garo live?": "The Garo live in Mymensingh."},
    )
    assert synthesizer.answer("Where do the Garo live?", [_triple()]) == (
        "The Garo live in Mymensingh."
    )
```

Add `NO_GROUNDED_ANSWER_MESSAGE` to the test file's `from rag import (...)` block.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `py -3.14 -m pytest tests/test_answer_synthesis.py -k "gated or unmarked or gate_off" -v`
Expected: FAIL — `ImportError: cannot import name 'NO_GROUNDED_ANSWER_MESSAGE' from 'rag'`

- [ ] **Step 3: Add the message constant**

In `rag.py`, immediately after the `relevance_gate_enabled` definition from Task 2:

```python
# Shown when retrieval found nothing, and when the relevance gate judged that
# nothing retrieved actually answers the question. One constant so the two
# paths cannot drift into saying different things about the same situation.
NO_GROUNDED_ANSWER_MESSAGE = (
    "I could not find enough connected evidence to answer that question. "
    "Try naming a specific person, place, event, or relationship."
)
```

- [ ] **Step 4: Use the constant for the existing empty-evidence return**

In `answer()`, replace line 890's inline literal:

```python
        if not triples:
            return "I could not find enough connected evidence to answer that question. Try naming a specific person, place, event, or relationship."
```

with:

```python
        if not triples:
            return NO_GROUNDED_ANSWER_MESSAGE
```

Leave `_fallback_answer`'s own shorter string alone — it is a different situation (templates produced nothing) on a path this change does not touch.

- [ ] **Step 5: Wire the gate into the success branch**

In `answer()`, replace the success branch (lines 919-924):

```python
            else:
                if response.status_code == 200:
                    text = response.json().get("response", "").strip()
                    if text:
                        return self._clean_response(text)
                break
```

with:

```python
            else:
                if response.status_code == 200:
                    text = response.json().get("response", "").strip()
                    if text:
                        if not relevance_gate_enabled():
                            return self._clean_response(text)
                        gated = self._parse_gated_response(text)
                        # A refusal is the intended output, not a failure:
                        # deliberately NOT _fallback_answer, whose templated
                        # triple soup is the off-topic padding being removed.
                        return gated if gated is not None else NO_GROUNDED_ANSWER_MESSAGE
                break
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `py -3.14 -m pytest tests/test_answer_synthesis.py -v`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `py -3.14 -m pytest -q`
Expected: 317 passed

- [ ] **Step 8: Commit**

```bash
git add rag.py tests/test_answer_synthesis.py
git commit -m "Act on the relevance gate's verdict in answer()

A RELEVANT: no, a missing marker or an unreadable one now returns the
honest no-evidence message instead of the model's prose. A refusal
deliberately does not route into _fallback_answer, whose templated triple
soup is the same off-topic padding the gate exists to remove.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Live verification and the ship/revert decision

**Files:**
- Modify: `KNOWN_LIMITATIONS.md` (#23)

**Interfaces:**
- Consumes: the deployed behaviour from Tasks 1-3.
- Produces: a go/no-go decision, and either a documented fix or a revert.

This task is the real gate. Both prior attempts at this problem passed review and were killed by live retesting (spec §1.1) — unit tests passing is not evidence this works.

- [ ] **Step 1: Turn the tunnel on**

```bash
bash scripts/tunnel_on.sh
```
Expected: ends with "Live AI is ON", and step 4/4 refreshes the TLS cert.

- [ ] **Step 2: Verify the refusal case locally**

```bash
py -3.14 rag.py --neo4j --query "How do the Garo trace family lineage and inheritance?"
```
Expected: the honest no-evidence message, **not** a paragraph mentioning Pütz or modernization.

- [ ] **Step 3: Verify the three known-strong questions still answer well**

```bash
py -3.14 rag.py --neo4j --query "Where do the Garo live?"
py -3.14 rag.py --neo4j --query "What language do the Garo speak?"
py -3.14 rag.py --neo4j --query "What challenges does the Garo community face?"
```
Expected: real grounded prose for all three. **Any refusal here is the over-refusal failure mode — stop and go to Step 7.**

- [ ] **Step 4: Check the mixed case**

```bash
py -3.14 rag.py --neo4j --query "What are the traditional religious beliefs of the Garo?"
```
Expected: either a grounded answer built on `GaroPeople -[HAVE_RELIGION]-> Sangsharek`, or an honest refusal. Both are acceptable. Fabricated bridging to bamboo floors is not — that is the 2026-10-07 failure and means stop.

- [ ] **Step 5: Deploy and verify on the hosted site**

Push, then trigger a manual deploy on Render (auto-deploy is unreliable for this repo — see `KNOWN_LIMITATIONS.md` and the 2026-10-07 notes), wait for "Deploy succeeded | Live", then:

```bash
curl -s -m 150 -X POST https://eat-40005-extraction.onrender.com/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How do the Garo trace family lineage and inheritance?"}'
```
Expected: the honest refusal. Retry once if the response returns in under ~5s with a templated answer — that is the known Render-to-Funnel `SSLEOFError` flakiness, not the gate.

- [ ] **Step 6: Document it (only if Steps 2-5 passed)**

Add to `KNOWN_LIMITATIONS.md` under #23, keeping the original text as the dated record per this document's editorial convention:

```markdown
**Partially fixed, 2026-10-08.** A relevance gate now makes the model emit
`RELEVANT: yes`/`RELEVANT: no` as its first line, and `rag.py` discards
everything after a "no" rather than trusting the model to stop writing --
which is what the two reverted attempts above asked for and did not get. An
unreadable or missing marker fails closed to the same refusal. Verified live
on the question that produced the fabricated Pütz (1991) attribution.

**What this does NOT fix.** It is all-or-nothing: a question with *mostly*
good evidence plus one irrelevant triple still gets synthesized, and the model
may still weave the irrelevant one in. Per-triple classification is the next
iteration (see the design's §5). The deterministic template fallback, used
when Ollama is unreachable, has no LLM to judge relevance and is unchanged --
and retrieval scoring cannot substitute, since measurement on 2026-10-08
showed the fabricating question outscoring two genuinely strong ones (22.05
vs 16.14 and 20.96). Set `SYNTHESIS_RELEVANCE_GATE=0` to disable.
```

Then commit:

```bash
git add KNOWN_LIMITATIONS.md
git commit -m "Record the relevance gate against KNOWN_LIMITATIONS #23

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Revert path (only if Steps 2-5 failed)**

Reverting is an acceptable outcome, consistent with how both 2026-10-07 attempts were handled. Fastest rollback on the deployed site, no code change:

```
Render dashboard > EAT-40005-Extraction > Environment > add SYNTHESIS_RELEVANCE_GATE=0 > save and deploy
```

To back the code out entirely:

```bash
git revert --no-commit <task-3-sha> <task-2-sha> <task-1-sha>
git commit -m "Revert the relevance gate: over-refused on live retest"
```

Then record what was observed in `KNOWN_LIMITATIONS.md` #23 as a third failed attempt, with the specific questions that over-refused — a reverted attempt with evidence is worth more to the next person than silence.

- [ ] **Step 8: Turn the tunnel off**

```bash
bash scripts/tunnel_off.sh
```
Expected: `tailscale funnel status` reports "No serve config".
