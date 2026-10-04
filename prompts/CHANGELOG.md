# Prompt changelog

## extraction_broad_v2 (2026-09-21)

Copy of the live `kg_extractor.make_extraction_prompt()` prompt (documented there as
"PR008 / Variant A round 4"), with one change: the opening framing "identify every ...
knowledge about the Garo/Mandi community" is reworded to "identify every ... knowledge
from this passage, in the Garo/Mandi cultural context." The domain scope is unchanged;
the implicit "the subject of every fact is the community" framing is removed, since it
actively worked against the prompt's own later instruction to match the sentence's own
specificity (see design spec §4 and §2 for the hub-collapse evidence this responds to).

## extraction_strict_tacit_v1 (2026-09-21)

New. Directly implements Tanjila's "try a strict tacit-only prompt" suggestion: an
explicit tacit-knowledge definition, worked examples and non-examples, and a rule to
output nothing rather than force a weak triple ("better to miss than to store wrong").
Also carries the readability rule that responds to the observed unreadable-triple
problem in the live Neo4j graph (see design spec §1.1 goal 3, §4).

## verify_tacit_evidence_v1 (2026-09-21) -- RETIRED 2026-09-29

Removed along with `verification/verify_pass.py`: the two-step verify pass was
already opt-in, showed no measured reduction in hallucination rate beyond the
deterministic gates on this corpus, and cost 8+ hours of CPU-Ollama time on a
single paper. The prompt text is recoverable from git history.


New. Second-step verification prompt for the two-step extract-then-verify pipeline
configuration. Asks evidence, tacit-knowledge, and readability together in one call
(mirroring `pruner/llm_judge.py`'s combined-question pattern), so the two-step design
costs exactly 2 LLM calls per candidate triple (extract, verify), not 3 or 4 (see
design spec §5, §1.2 zero-cost constraint).
