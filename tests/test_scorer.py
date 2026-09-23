from eval.scorer import jaccard_similarity, match_lenient, match_strict, normalize


def test_normalize_lowercases_and_strips():
    assert normalize(" GaroCommunity ", "WEARS", " Lungis") == ("garocommunity", "wears", "lungis")


def test_match_strict_exact_after_normalization():
    a = ("GaroCommunity", "WEARS", "Lungis")
    b = ("garocommunity", "wears", "lungis")
    assert match_strict(a, b) is True


def test_match_strict_different_object_fails():
    a = ("GaroCommunity", "WEARS", "Lungis")
    b = ("GaroCommunity", "WEARS", "Sarees")
    assert match_strict(a, b) is False


def test_jaccard_identical_triples_is_one():
    a = ("GaroCommunity", "WEARS", "Lungis")
    assert jaccard_similarity(a, a) == 1.0


def test_jaccard_unrelated_triples_is_zero():
    a = ("GaroCommunity", "LIVES_IN", "Bangladesh")
    b = ("NGOs", "PROMOTE", "Education")
    assert jaccard_similarity(a, b) == 0.0


def test_match_lenient_catches_true_paraphrase():
    ground_truth = ("GaroMen", "WEARS", "Lungis")
    extracted = ("GaroCommunity", "WEAR", "Lungis")
    assert jaccard_similarity(ground_truth, extracted) > 0.3
    assert match_lenient(ground_truth, extracted) is True


def test_match_lenient_rejects_different_fact_same_subject():
    a = ("GaroCommunity", "LIVES_IN", "MountainsOfBangladesh")
    b = ("GaroCommunity", "MIGRATED_FROM", "Tibet")
    assert jaccard_similarity(a, b) < 0.3
    assert match_lenient(a, b) is False


def test_match_lenient_rejects_second_different_fact_same_subject():
    a = ("GaroCommunity", "LIVES_IN", "MountainsOfBangladesh")
    b = ("GaroCommunity", "WEARS", "Sarees")
    assert jaccard_similarity(a, b) < 0.3
    assert match_lenient(a, b) is False
