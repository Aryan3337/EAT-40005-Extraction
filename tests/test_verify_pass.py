from verification.verify_pass import (
    VERIFY_HIGH_THRESHOLD,
    VERIFY_LOW_THRESHOLD,
    _parse_judge_response,
    verify_triple,
)


def test_parse_judge_response_valid_json():
    text = '{"decision": "keep", "confidence": 0.85, "reason": "well supported"}'
    decision, confidence, reason = _parse_judge_response(text)
    assert decision == "keep"
    assert confidence == 0.85
    assert reason == "well supported"


def test_parse_judge_response_json_embedded_in_prose():
    text = 'Sure, here is my answer: {"decision": "reject", "confidence": 0.1, "reason": "not evidenced"}'
    decision, confidence, reason = _parse_judge_response(text)
    assert decision == "reject"
    assert confidence == 0.1


def test_parse_judge_response_unparseable_falls_back_to_reject():
    decision, confidence, reason = _parse_judge_response("no json here at all")
    assert decision == "reject"
    assert confidence == 0.0
    assert reason == "unparseable_judge_response"


def test_verify_triple_high_confidence_keeps():
    def fake_judge(subject, predicate, obj, source_sentence):
        return "keep", 0.9, "clearly supported"

    result = verify_triple("GaroCommunity", "WEARS", "Lungis", "Garo men wear lungis.", fake_judge)
    assert result.band == "keep"
    assert result.confidence == 0.9


def test_verify_triple_low_confidence_rejects():
    def fake_judge(subject, predicate, obj, source_sentence):
        return "reject", 0.1, "not evidenced"

    result = verify_triple("Respondents", "KNOWN_ORIGIN", "Tibet", "Some respondents said Tibet.", fake_judge)
    assert result.band == "reject"


def test_verify_triple_mid_confidence_goes_to_review():
    def fake_judge(subject, predicate, obj, source_sentence):
        return "reject", 0.5, "borderline tacit knowledge"

    result = verify_triple("GaroCommunity", "ATE", "Rice", "Some claim about rice.", fake_judge)
    assert result.band == "review"


def test_thresholds_are_ordered():
    assert VERIFY_LOW_THRESHOLD < VERIFY_HIGH_THRESHOLD
