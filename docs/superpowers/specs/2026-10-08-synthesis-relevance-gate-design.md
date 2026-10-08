# Synthesis Relevance Gate — Stopping Fabricated Connections in Chatbot Answers

**Project:** EAT40005 Capstone, Group P85 — Mandi/Garo Knowledge Graph Extraction
**Date:** 2026-10-08
**Status:** Approved for planning (brainstorming phase complete; implementation plan to follow via writing-plans)

## 1. Context and goals

The chatbot's answer synthesis (`rag.py`'s `AnswerSynthesizer`) is the system's
user-facing feature: it takes the triples retrieval returns and writes the sentence a
visitor actually reads. Measured live on 2026-10-08 against the hosted deployment, it
fabricates connections between unrelated facts when the graph has no real evidence for
the question asked.

The reproducing case, captured live through the real UI. Question: *"How do the Garo
trace family lineage and inheritance?"* Answer returned:

> "The evidence provided does not directly answer how the Garo trace family lineage and
> inheritance. However, it is mentioned that traditional practices are being modified in
> response to modernization **(which may include family structures and inheritance)**, **as
> stated in Pütz (1991) who identified family as one of the domains of study.** The Garo
> community resides primarily in the Garo Hills of Meghalaya, and their culture, beliefs,
> customs, lifestyle, and traditions are significant aspects of their identity..."

Two distinct defects, both in bold above:

1. **Invented inference.** "(which may include family structures and inheritance)" is not
   in the evidence. The source triple (`TraditionalInheritancePractices -[ARE_MODIFIABLE]->
   Modernization`) cites a *hypothetical illustrative* sentence ("In a Garo village
   experiencing rapid modernization, a family deliberates on how to adapt..."), not a
   reported finding.
2. **Fabricated citation attribution.** "as stated in Pütz (1991) who identified family as
   one of the domains of study" implies Pütz supports the modernization claim. It does
   not. `Pütz_1991 -[IDENTIFIED_DOMAINS]-> Family` is a sociolinguistics framework about
   which *settings* a language is used in (family, friendship, church, clubs, work). The
   model merged two facts that share only the keyword "family" into one sentence implying
   a connection neither states. Misattributing a named academic citation is worse than
   vague hedging, because it reads as sourced.

This is `KNOWN_LIMITATIONS.md` #23 ("the synthesizer sometimes invents connections between
real, unrelated facts"), found 2026-10-07, recurring on a new question.

### 1.1 Why this is not a retry of what already failed

Two prompt-only fixes were attempted on 2026-10-07 and **both failed on live retesting and
were reverted** rather than shipped:

1. An explicit "do not speculate about connections the evidence does not state"
   instruction with forbidden-phrasing examples. The model speculated almost identically
   on rerun.
2. A stronger rewrite with a forbidden-word list, a worked wrong/right example, and an
   instruction to omit off-topic evidence entirely. The model made the same connection
   anyway, adding only a self-aware hedge — the instruction to omit was not followed.

Both asked the model to **self-regulate its own elaboration inside free-flowing prose** —
an open-ended instruction with no mechanical check. This design does not ask that. It asks
for one narrow binary decision as the first line of output, and **enforces the consequence
in code.**

The 2026-10-08 failure is direct evidence that this distinction matters: the model's own
answer *opened* with "The evidence provided does not directly answer..." It judged relevance
correctly, then kept writing anyway. The judgment was never the broken part. The
unconstrained continuation was.

### 1.2 Measurement that ruled out the obvious alternative

The intuitive fix — gate on retrieval score, refusing to synthesize when the evidence
scores too low — was **tested against the live graph before being proposed, and
disproven.** Top `score_triple_weighted` scores:

| Question | Known answer quality | Top score |
|---|---|---|
| How do the Garo trace family lineage and inheritance? | **Fabricated** | **22.05** |
| What are the traditional religious beliefs of the Garo? | Thin | 16.25 |
| Where do the Garo live? | **Strong** | 16.14 |
| What challenges does the Garo community face? | Strong | 20.96 |
| What language do the Garo speak? | Strong | 23.97 |

The fabricating question scores **higher** than two genuinely strong questions. No absolute
threshold separates them. The cause is structural: `keyword_weights` is smoothed IDF, so it
rewards keyword *rarity*. "Inheritance" is rare in this corpus, so a single coincidental hit
on a hypothetical sentence outranks solid, common-vocabulary evidence. This extends
`KNOWN_LIMITATIONS.md` #22's finding (relative thresholds fail) to absolute thresholds too.

A second finding from the same measurement, worth recording because it changes what
"fix this" can mean: **the two thin cases are not the same problem.** For the religion
question, real evidence exists (`GaroPeople -[HAVE_RELIGION]-> Sangsharek`, score 15.32) and
is merely outranked — a ranking problem. For the inheritance question, **the graph contains
no information about how Garo inheritance actually works.** No retrieval change produces a
good substantive answer to a question the corpus cannot answer. The correct ceiling there is
an honest refusal.

### 1.3 Success criteria

Agreed with the project owner: **never fabricate a connection, even at the cost of more
honest refusals.** A thin or absent answer is acceptable; a confident-sounding invented
connection is not. This matches the precision-over-recall standard already applied to
extraction gating.

### 1.4 Constraints

- **Zero marginal cost and local inference only.** No third-party model provider, per the
  commitment recorded in the project's data-privacy constraint. Uses the existing local
  Ollama reached over the Tailscale Funnel tunnel.
- **No added LLM round-trips.** Measured 2026-10-08: 2 of 3 real hosted requests failed
  outright with `SSLEOFError` on the Render-to-Funnel path. Each additional call is another
  independent chance of total failure. This design stays at one call.
- **Must be reversible without a code change.** Demo is 2026-10-09.

### 1.5 Non-goals

- Fixing the deterministic template fallback path (used when Ollama is unreachable). It has
  no LLM to judge relevance, and §1.2 proves keyword scoring cannot substitute. Out of scope.
- Per-triple filtering of partially-relevant evidence sets (see §7, Approach 2).
- Entity resolution / predicate-fit filtering at the retrieval layer (`KNOWN_LIMITATIONS.md`
  #4). The real long-term fix; multi-day work, explicitly post-demo.
- Any change to retrieval ranking, the graph, or the Flutter client.

## 2. Design

All changes in `rag.py`'s `AnswerSynthesizer`.

### 2.1 The gate instruction

Prepended to the prompt built by `_build_prompt()`:

```
Before answering, judge whether the evidence below directly answers the question.
Your FIRST line must be exactly one of:
RELEVANT: yes
RELEVANT: no
Write "no" if the evidence only touches the topic indirectly, mentions a
related word, or would require you to infer a connection the evidence does
not itself state. If "no", write nothing after that line.
If "yes", write the answer below it, using only evidence that directly
supports it.
```

### 2.2 Parsing and the hard discard

New `_parse_gated_response(text) -> str | None`. Order of operations is load-bearing:

1. **Run the existing `_clean_response()` on the raw model output first, then parse the
   marker from its result.** Two reasons this ordering is required, not incidental:
   `deepseek-r1:7b` emits `<think>...</think>` reasoning before anything else (without
   stripping it the marker is never on the first line), and `_clean_response` also strips a
   leading `Answer:`/`Response:` prefix, so an output like `Answer: RELEVANT: yes` still
   leaves `RELEVANT: yes` as line one. Reuse the method whole; do not duplicate its regexes.
2. Take the first non-empty line; match case-insensitively against `RELEVANT:\s*(yes|no)`.
3. `no` → return `None`. **Everything after the marker is discarded in code.** The model is
   never trusted to stop on its own.
4. `yes` → strip the marker line, return the remainder.
5. Missing marker, unparseable, or `yes` with an empty body → return `None`. **Fails
   closed**, per §1.3.

### 2.3 Refusal output

A module-level constant holding the existing string, so both this path and
`_fallback_answer`'s empty-evidence branch share one source of truth:

> "I could not find enough connected evidence to answer that question."

A refusal **must not** route through `_fallback_answer(triples)`. That renders templated
triple soup — the same off-topic padding this change exists to remove. Bare message only.

### 2.4 Kill switch

`SYNTHESIS_RELEVANCE_GATE`, read from the environment, **defaulting to on**. Disabled when
set to a value in the existing `_FALSEY` set (`""`, `"0"`, `"false"`, `"no"`, `"off"`) —
reusing `llm_endpoint.py`'s convention rather than inventing a second one.

When disabled, behaviour is exactly today's: no gate instruction in the prompt, no marker
parsing, model prose returned as-is. Set it on Render and redeploy (~30s) to revert without
a code change or git access.

This is a **deploy-level kill switch, not a per-request fallback.** When the gate fires
`no`, the refusal is the intended output; there is deliberately no path that falls back to
returning the model's prose on a `no`, since that is the fabrication being removed.

### 2.5 Unchanged interactions

- **Cached answers bypass the gate.** `answer()` checks `answer_cache` before any model
  call; the three cached demo answers were human-verified. No change.
- **Connection failure still uses `_fallback_answer(triples)`.** The gate applies only when
  a model response was actually received.

## 3. Testing

**Unit.** Parser: `yes` + prose; `no` + trailing prose (asserting the prose is discarded);
missing marker; malformed marker; `<think>` wrapper preceding the marker; case and
whitespace variants; `yes` with empty body. Prompt: gate instruction present when enabled,
absent when disabled. `answer()`: returns the refusal constant on `no` and does **not** call
`_fallback_answer`; with the kill switch off, returns prose unmodified.

**Live — this is the ship gate, not a formality.** Per this project's established practice
(both prior attempts at this problem were caught by live retesting after passing review):

1. The inheritance question must now refuse cleanly.
2. The three known-strong questions (location, language, challenges) must **still answer
   well**. Any regression here means revert.
3. The religion question as the mixed case: real evidence at rank 2 behind an irrelevant
   rank-1 hit.

## 4. Risks

**Over-refusal is the failure mode this introduces.** A trigger-happy `no` makes strong
questions refuse and the demo worse than before. Live-testing the three strong questions is
mandatory before committing.

**Format non-compliance.** If the model will not reliably emit the marker, fail-closed
means over-refusal across the board. The correct response is to revert — consistent with how
both 2026-10-07 attempts were handled — not to weaken the fail-closed rule into trusting
unmarked prose.

## 5. Follow-up work (not this change)

- **Approach 2 — per-triple relevance classification.** Classify each retrieved triple
  individually, then synthesize from only those marked relevant. Catches *partially* bridged
  answers (good evidence padded with one irrelevant fact), which §2's all-or-nothing gate
  cannot. Costs a second round-trip; deferred on the §1.4 reliability constraint. Next
  iteration if time allows before the demo.
- **Entity resolution / predicate-fit filtering** (`KNOWN_LIMITATIONS.md` #4). The real fix,
  post-demo.
- **The corpus coverage gap** surfaced in §1.2: some questions have no answer in the graph at
  all. A gate makes the system honest about that; only new extraction makes it answerable.
