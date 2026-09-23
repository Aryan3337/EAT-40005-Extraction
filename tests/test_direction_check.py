from verification.direction_check import check_direction


def test_correctly_directed_prohibits_not_flagged():
    result = check_direction("VillageCouncilRule", "PROHIBITS", "FishingInTheArea")
    assert result.flagged is False


def test_reversed_prohibits_is_flagged():
    result = check_direction("FishingArea", "PROHIBITS", "VillageCouncilRule")
    assert result.flagged is True
    assert "PROHIBITS" in result.reason


def test_reversed_governs_is_flagged():
    result = check_direction("LandDispute", "GOVERNS", "ClanCouncil")
    assert result.flagged is True


def test_unknown_predicate_never_flagged():
    result = check_direction("GaroCommunity", "WEARS", "Lungis")
    assert result.flagged is False
    assert result.reason is None


def test_ambiguous_case_not_flagged():
    # Neither side matches the lexicon's keyword shape at all -- silence,
    # not a guess.
    result = check_direction("SomeGroup", "REQUIRES", "SomethingElse")
    assert result.flagged is False
