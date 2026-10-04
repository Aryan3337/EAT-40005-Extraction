from eval.hallucination import check_row_hallucinated, compute_hallucination_rate


PAGE_TEXTS = {
    3: (
        "Garo men wear lungis, genjis, trousers, and shirts. Garo women "
        "usually wear orna, sarees, blouses, kamij, petticoats, salwars."
    ),
}


def _row(page_number, subject, predicate, obj, sentence_ref):
    return {
        "page_number": str(page_number),
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "sentence_ref": sentence_ref,
    }


def test_grounded_row_with_genuine_quote_is_not_flagged():
    row = _row(3, "GaroMen", "WEARS", "Trousers", "<Garo men wear lungis, genjis, trousers, and shirts.>")
    assert check_row_hallucinated(row, PAGE_TEXTS) == []


def test_fabricated_quote_is_flagged_even_if_claim_matches_its_own_quote():
    row = _row(
        3, "Fishman_Domain_Approach", "USED_IN", "Language_Maintenance_Research",
        "<The passage mentions Fishman's Domain Approach was used in language maintenance research.>",
    )
    reasons = check_row_hallucinated(row, PAGE_TEXTS)
    assert reasons
    assert any("not found verbatim" in r for r in reasons)


def test_real_quote_but_ungrounded_claim_is_flagged():
    row = _row(3, "GaroCommunity", "PRACTICES", "MatrilinealInheritance",
               "<Garo men wear lungis, genjis, trousers, and shirts.>")
    reasons = check_row_hallucinated(row, PAGE_TEXTS)
    assert reasons
    assert any("MatrilinealInheritance" in r for r in reasons)


def test_missing_page_text_flags_via_grounding_fail_closed():
    row = _row(99, "GaroMen", "WEARS", "Trousers", "<Garo men wear trousers.>")
    reasons = check_row_hallucinated(row, PAGE_TEXTS)
    assert reasons


def test_compute_hallucination_rate_over_multiple_rows():
    rows = [
        _row(3, "GaroMen", "WEARS", "Trousers", "<Garo men wear lungis, genjis, trousers, and shirts.>"),
        _row(3, "GaroMen", "WEARS", "Shirts", "<Garo men wear lungis, genjis, trousers, and shirts.>"),
        _row(3, "GaroCommunity", "PRACTICES", "MatrilinealInheritance",
             "<Garo men wear lungis, genjis, trousers, and shirts.>"),
    ]
    report = compute_hallucination_rate(rows, PAGE_TEXTS)
    assert report.total_count == 3
    assert report.flagged_count == 1
    assert report.hallucination_rate == 1 / 3
    assert len(report.flagged_rows) == 1
    assert report.flagged_rows[0]["subject"] == "GaroCommunity"


def test_compute_hallucination_rate_empty_input():
    report = compute_hallucination_rate([], PAGE_TEXTS)
    assert report.total_count == 0
    assert report.hallucination_rate == 0.0
    assert report.flagged_rows == []
    assert report.citation_coverage == 0.0


def test_citation_coverage_tracks_rows_with_no_sentence_ref():
    # A row with no sentence_ref at all can't be judged for grounding --
    # that's a data gap, not evidence of fabrication. citation_coverage lets
    # a caller tell "100% hallucinated" apart from "0% of rows had a
    # citation to check in the first place" (a real, observed failure mode:
    # some extraction prompts never populate sentence_ref).
    rows = [
        _row(3, "GaroMen", "WEARS", "Trousers", "<Garo men wear lungis, genjis, trousers, and shirts.>"),
        _row(3, "GaroMen", "WEARS", "Shirts", ""),
        _row(3, "GaroCommunity", "WEARS", "Saree", ""),
    ]
    report = compute_hallucination_rate(rows, PAGE_TEXTS)
    assert report.citation_coverage == 1 / 3
    # both no-citation rows are still counted as flagged (fail closed) --
    # coverage is what tells a reader the rate is on a thin evidence base.
    assert report.flagged_count == 2
