from verification.wellformedness_check import check_wellformedness


def test_clean_triple_not_flagged():
    result = check_wellformedness("GaroCommunity", "WEARS", "Lungis")
    assert result.flagged is False
    assert result.reasons == []


def test_dangling_word_appositive_bug_is_flagged():
    # Real, previously-observed case: subject_specificity.py's own comments
    # document this exact mis-chunked-appositive entity name.
    result = check_wellformedness("PioneeringGaroScholarThe", "WROTE", "Book")
    assert result.flagged is True
    assert any("dangling" in reason for reason in result.reasons)


def test_oversized_entity_is_flagged():
    result = check_wellformedness(
        "VeryOldTraditionalGaroHouseholdStructure", "HAS_FEATURE", "ThatchedRoof"
    )
    assert result.flagged is True
    assert any("6 words" in reason for reason in result.reasons)


def test_overlong_predicate_is_flagged():
    result = check_wellformedness(
        "GaroCommunity", "IS_USED_IN_THE_TRADITIONAL_CONTEXT_OF", "Ceremony"
    )
    assert result.flagged is True
    assert any("segments" in reason for reason in result.reasons)


def test_simple_predicate_not_flagged():
    result = check_wellformedness("GaroCommunity", "HAS_PROFESSION", "Farmer")
    assert result.flagged is False
