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


from eval.scorer import score


def test_score_perfect_match():
    ground_truth = [("GaroCommunity", "WEARS", "Lungis")]
    extracted = [("GaroCommunity", "WEARS", "Lungis")]
    report = score(extracted, ground_truth, num_pages=1)
    assert report.tp_strict == 1
    assert report.fp_strict == 0
    assert report.fn_strict == 0
    assert report.precision_strict == 1.0
    assert report.recall_strict == 1.0
    assert report.f1_strict == 1.0
    assert report.gt_miss_rate == 0.0
    assert report.triples_per_page == 1.0


def test_score_one_gt_miss():
    # "Respondents KNOWN_ORIGIN Tibet" has no exact match in this tiny
    # ground truth -- gt_miss_rate counts that as a miss. It says nothing
    # about whether the triple is actually grounded/true; see
    # eval/hallucination.py for that separate question.
    ground_truth = [("GaroCommunity", "WEARS", "Lungis")]
    extracted = [
        ("GaroCommunity", "WEARS", "Lungis"),
        ("Respondents", "KNOWN_ORIGIN", "Tibet"),
    ]
    report = score(extracted, ground_truth, num_pages=1)
    assert report.tp_strict == 1
    assert report.fp_strict == 1
    assert report.fn_strict == 0
    assert report.gt_miss_rate == 0.5
    assert report.triples_per_page == 2.0


def test_score_lenient_catches_what_strict_misses():
    ground_truth = [("GaroMen", "WEARS", "Lungis")]
    extracted = [("GaroCommunity", "WEAR", "Lungis")]
    report = score(extracted, ground_truth, num_pages=1)
    assert report.tp_strict == 0
    assert report.tp_lenient == 1
    assert report.recall_lenient == 1.0


def test_score_no_extraction_gives_zero_precision_and_no_gt_miss():
    ground_truth = [("GaroCommunity", "WEARS", "Lungis")]
    report = score([], ground_truth, num_pages=1)
    assert report.tp_strict == 0
    assert report.fn_strict == 1
    assert report.precision_strict == 0.0
    assert report.gt_miss_rate == 0.0


def test_score_greedy_matching_is_one_to_one():
    # Two identical extracted triples must not both claim the single
    # ground-truth triple.
    ground_truth = [("GaroCommunity", "WEARS", "Lungis")]
    extracted = [
        ("GaroCommunity", "WEARS", "Lungis"),
        ("GaroCommunity", "WEARS", "Lungis"),
    ]
    report = score(extracted, ground_truth, num_pages=1)
    assert report.tp_strict == 1
    assert report.fp_strict == 1
