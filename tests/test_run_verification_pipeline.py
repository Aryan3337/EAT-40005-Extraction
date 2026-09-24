import csv

from run_verification_pipeline import run


def _fake_judge(subject, predicate, obj, source_sentence):
    if subject == "GaroCommunity" and predicate == "ATE":
        return "reject", 0.5, "borderline tacit knowledge"
    return "keep", 0.9, "fine"


def test_run_verification_pipeline_writes_expected_outputs(tmp_path):
    csv_path = tmp_path / "sample.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["GaroCommunity", "WEARS", "Lungis", "Garo men wear lungis."])
        writer.writerow(["FishingArea", "PROHIBITS", "VillageCouncilRule", "The rule prohibits fishing."])
        writer.writerow(["PioneeringGaroScholarThe", "WROTE", "Book", "A scholar wrote a book."])
        writer.writerow(["GaroCommunity", "ATE", "Rice", "Some claim about rice."])

    summary = run(
        str(csv_path), run_verify=True, run_direction=True, run_wellformed=True,
        judge_fn=_fake_judge,
    )

    # Hard gate: a flagged row is excluded from refined even when verify
    # bands it "keep" -- flags are still visible in their own audit files,
    # just no longer double as an allow-list. Only row 1 (GaroCommunity
    # WEARS Lungis) is both "keep" and unflagged.
    assert summary == {
        "refined": 1,
        "reviewed_out": 1,
        "direction_flags": 1,
        "wellformedness_flags": 1,
        "grounding_flags": 0,
    }

    assert (tmp_path / "sample_refined.csv").exists()
    assert (tmp_path / "sample_reviewed_out.csv").exists()
    assert (tmp_path / "sample_direction_flags.csv").exists()
    assert (tmp_path / "sample_wellformedness_flags.csv").exists()

    with open(tmp_path / "sample_reviewed_out.csv", newline="", encoding="utf-8") as f:
        reviewed_rows = list(csv.DictReader(f))
    assert reviewed_rows[0]["subject"] == "GaroCommunity"
    assert reviewed_rows[0]["predicate"] == "ATE"


def test_run_verification_pipeline_hard_gates_flagged_rows_even_without_verify(tmp_path):
    csv_path = tmp_path / "sample2.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["FishingArea", "PROHIBITS", "VillageCouncilRule", "The rule prohibits fishing."])

    summary = run(str(csv_path), run_verify=False, run_direction=True, run_wellformed=False)

    # Direction/wellformedness checks are a hard gate on refined, independent
    # of whether --verify ran -- no human downstream to catch a flagged row
    # that slipped through, so it must never reach refined.
    assert summary["refined"] == 0
    assert summary["direction_flags"] == 1
    assert not (tmp_path / "sample2_reviewed_out.csv").exists()


def test_run_verification_pipeline_unflagged_row_still_reaches_refined_without_verify(tmp_path):
    csv_path = tmp_path / "sample2b.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["GaroCommunity", "WEARS", "Lungis", "Garo men wear lungis."])

    summary = run(str(csv_path), run_verify=False, run_direction=True, run_wellformed=False)

    assert summary["refined"] == 1
    assert summary["direction_flags"] == 0


def test_run_verification_pipeline_passes_verify_samples_through_to_judge_fn(tmp_path):
    csv_path = tmp_path / "sample4.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["GaroCommunity", "WEARS", "Lungis", "Garo men wear lungis."])

    calls = []

    def counting_judge(subject, predicate, obj, source_sentence):
        calls.append(1)
        return "keep", 0.9, "fine"

    run(
        str(csv_path), run_verify=True, run_direction=False, run_wellformed=False,
        judge_fn=counting_judge, verify_samples=3,
    )

    assert len(calls) == 3


def test_run_verification_pipeline_verify_samples_defaults_to_one(tmp_path):
    csv_path = tmp_path / "sample5.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["GaroCommunity", "WEARS", "Lungis", "Garo men wear lungis."])

    calls = []

    def counting_judge(subject, predicate, obj, source_sentence):
        calls.append(1)
        return "keep", 0.9, "fine"

    run(
        str(csv_path), run_verify=True, run_direction=False, run_wellformed=False,
        judge_fn=counting_judge,
    )

    assert len(calls) == 1


def test_run_verification_pipeline_hard_gates_ungrounded_rows(tmp_path):
    csv_path = tmp_path / "sample6.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        # "BottleGourd" never appears in the sentence -- fabricated specific.
        writer.writerow(["GaroCommunity", "HAS_INGREDIENT", "BottleGourd", "They enjoy a variety of vegetables."])
        writer.writerow(["GaroMen", "WEARS", "Lungis", "Garo men wear lungis."])

    summary = run(str(csv_path), run_verify=False, run_direction=False, run_wellformed=False, run_grounding=True)

    assert summary["refined"] == 1
    assert summary["grounding_flags"] == 1
    assert (tmp_path / "sample6_grounding_flags.csv").exists()


def test_run_verification_pipeline_grounding_check_off_by_default(tmp_path):
    csv_path = tmp_path / "sample7.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["GaroCommunity", "HAS_INGREDIENT", "BottleGourd", "They enjoy a variety of vegetables."])

    summary = run(str(csv_path), run_verify=False, run_direction=False, run_wellformed=False)

    assert summary["refined"] == 1
    assert summary["grounding_flags"] == 0


def test_run_verification_pipeline_warns_when_verify_has_no_sentence_data(tmp_path, capsys):
    # No sentence_ref/passage column at all -- e.g. a CSV shaped like
    # test_extraction_variants.py's output, not kg_extractor.py's.
    csv_path = tmp_path / "sample3.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["page_number", "subject", "predicate", "object", "confidence_score"])
        writer.writerow(["3", "GaroCommunity", "WEARS", "Lungis", "0.9"])

    run(str(csv_path), run_verify=True, run_direction=False, run_wellformed=False, judge_fn=_fake_judge)

    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "sentence_ref" in captured.err
