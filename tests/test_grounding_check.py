from verification.grounding_check import check_grounding


def test_subject_and_object_both_present_not_flagged():
    result = check_grounding("GaroMen", "Trousers", "Garo men wear lungis, genjis, trousers, and shirts.")
    assert result.flagged is False
    assert result.reasons == []


def test_object_not_in_sentence_is_flagged():
    result = check_grounding("GaroCommunity", "BottleGourd", "They enjoy a variety of vegetables such as brinjal.")
    assert result.flagged is True
    assert any("Object" in reason and "BottleGourd" in reason for reason in result.reasons)


def test_subject_not_in_sentence_is_flagged():
    result = check_grounding("FloatingIslandCommunity", "Rice", "The primary food of Garo people is rice.")
    assert result.flagged is True
    assert any("Subject" in reason and "FloatingIslandCommunity" in reason for reason in result.reasons)


def test_empty_sentence_ref_is_flagged():
    # Fail closed: no source sentence means no evidence, so it cannot be
    # considered grounded regardless of what the entity names say.
    result = check_grounding("GaroCommunity", "Rice", "")
    assert result.flagged is True
    assert any("sentence_ref" in reason.lower() for reason in result.reasons)


def test_matching_is_case_insensitive():
    result = check_grounding("GaroMen", "Lungis", "GARO MEN WEAR LUNGIS.")
    assert result.flagged is False


def test_partial_multiword_entity_match_is_flagged():
    # Only "matrilineal" appears in the sentence -- "system" never does.
    # Every word of a multi-word entity must be grounded, not just one.
    result = check_grounding(
        "GaroCommunity", "MatrilinealSystem",
        "The community traditionally follows a matrilineal approach to inheritance.",
    )
    assert result.flagged is True
    assert any("MatrilinealSystem" in reason for reason in result.reasons)
