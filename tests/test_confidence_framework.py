"""Regression guard for the confidence framework's token budget.

THE BUG THIS LOCKS IN: `num_predict` was 256. The model has to emit a complete
JSON object scoring four criteria, each with a justification sentence, and 256
tokens cut it off mid-structure -- so `parse_model_response` failed on every
chunk of every paper, all four model-scored criteria fell to 0, and papers came
out REJECTED at about 5/100.

That is the real cause of the `5, 5, 5` scores in `confidence_logs/rejected/`.
It was previously read as an unreachable Ollama; it is a token budget, and it
fired deterministically rather than intermittently.

Measured on garo_1.pdf chunk 1 with mistral:7b:
    256  -> 876 chars, truncated, parse FAILED
    1024 -> 1561 chars, parse OK, 4 criteria

No Ollama needed here: these drive the parser directly with captured shapes.
"""

import json

from confidence_framework import MODEL_RESPONSE_TOKEN_BUDGET, parse_model_response


def _complete_response(criteria=4):
    return json.dumps({
        "criteria": [
            {
                "name": f"Criterion {i}",
                "score": 20,
                "max_score": 25,
                "justification": "A sentence explaining the score.",
                "flags": [],
            }
            for i in range(criteria)
        ]
    })


def test_a_complete_response_parses():
    assert parse_model_response(_complete_response()) is not None


def test_a_response_truncated_mid_object_does_not_parse():
    # The exact shape 256 tokens produced: valid up to a point, then cut off
    # with no closing brackets.
    truncated = _complete_response()[:400]
    assert not truncated.endswith("}")
    assert parse_model_response(truncated) is None


def test_the_token_budget_is_large_enough_for_a_full_response():
    # 1024 was measured as sufficient and 256 as insufficient. Anything at or
    # below 256 reintroduces the bug silently -- every paper rejected at ~5/100
    # with no error, because a truncated response is skipped rather than raised.
    assert MODEL_RESPONSE_TOKEN_BUDGET >= 1024


def test_markdown_fenced_json_still_parses():
    # The prompt asks for bare JSON but models often wrap it in a code fence.
    assert parse_model_response("```json\n" + _complete_response() + "\n```") is not None
