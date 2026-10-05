#!/usr/bin/env python3
"""Pre-compute answers for the demo's scripted questions.

WHY: measured 2026-10-05, real Ollama synthesis calls were taking 90s+ on
this machine -- 2x the ~40s benchmark from earlier sessions, for reasons not
yet diagnosed -- and falling back to the ugly templated answer when they
exceeded even a 90s timeout. The demo's suggested prompts (see
flutter_application/lib/features/chat/chat_page.dart's _examplePrompts) are
known in advance, so this runs each one for real -- once, here, not during
the demo -- and writes the result to data/demo_answer_cache.json.
AnswerSynthesizer.answer serves a cached entry instantly instead of calling
Ollama; anything not in the cache still goes through live synthesis
unchanged.

Run this again whenever _examplePrompts changes, or whenever the production
graph (data/production_graph/) is reloaded with different content, since a
cached answer only reflects the evidence that was in the graph when it was
generated.

    python generate_demo_answer_cache.py
"""

import json
import sys
from pathlib import Path

from rag import AnswerSynthesizer, DEMO_ANSWER_CACHE_PATH, Neo4jRAGSkeleton

# Must match flutter_application/lib/features/chat/chat_page.dart's
# _examplePrompts exactly -- that is what a demo presenter actually clicks.
SCRIPTED_QUESTIONS = [
    "Where do the Garo live?",
    "What language do the Garo speak?",
    "What challenges does the Garo community face?",
]

# The exact text _fallback_answer's output always starts with -- a cheap,
# reliable way to detect a timed-out call rather than a real one, since both
# return 200 with a string and look superficially similar otherwise.
_FALLBACK_PREFIX = "Based on the available knowledge, "


def main() -> int:
    skeleton = Neo4jRAGSkeleton()
    # answer_cache={} forces a live call for every question here, regardless
    # of what is already on disk -- the whole point of this script is to
    # regenerate that file.
    synthesizer = AnswerSynthesizer(answer_cache={})

    cache = {}
    problems = []
    try:
        for question in SCRIPTED_QUESTIONS:
            print(f"Querying: {question}")
            triples = skeleton.query(question)
            print(f"  {len(triples)} triples retrieved")
            if not triples:
                problems.append(f"{question!r}: no triples retrieved, nothing to cache")
                continue

            answer = synthesizer.answer(question, triples)
            if answer.startswith(_FALLBACK_PREFIX):
                problems.append(
                    f"{question!r}: synthesis timed out and fell back to the "
                    f"template -- not caching a non-answer. Re-run this script."
                )
                continue

            print(f"  -> {answer}\n")
            cache[question] = answer
    finally:
        skeleton.close()

    if problems:
        print("\nProblems:")
        for problem in problems:
            print(f"  - {problem}")

    if not cache:
        print("\nNothing to write.")
        return 1

    DEMO_ANSWER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEMO_ANSWER_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\nWrote {len(cache)} of {len(SCRIPTED_QUESTIONS)} answers to {DEMO_ANSWER_CACHE_PATH}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
