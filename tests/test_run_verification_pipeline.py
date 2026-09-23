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

    assert summary == {
        "refined": 3,
        "reviewed_out": 1,
        "direction_flags": 1,
        "wellformedness_flags": 1,
    }

    assert (tmp_path / "sample_refined.csv").exists()
    assert (tmp_path / "sample_reviewed_out.csv").exists()
    assert (tmp_path / "sample_direction_flags.csv").exists()
    assert (tmp_path / "sample_wellformedness_flags.csv").exists()

    with open(tmp_path / "sample_reviewed_out.csv", newline="", encoding="utf-8") as f:
        reviewed_rows = list(csv.DictReader(f))
    assert reviewed_rows[0]["subject"] == "GaroCommunity"
    assert reviewed_rows[0]["predicate"] == "ATE"


def test_run_verification_pipeline_without_verify_keeps_all_flagged_rows_too(tmp_path):
    csv_path = tmp_path / "sample2.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["FishingArea", "PROHIBITS", "VillageCouncilRule", "The rule prohibits fishing."])

    summary = run(str(csv_path), run_verify=False, run_direction=True, run_wellformed=False)

    # Flagging never removes a triple from refined -- flag-only, never auto-delete.
    assert summary["refined"] == 1
    assert summary["direction_flags"] == 1
    assert not (tmp_path / "sample2_reviewed_out.csv").exists()


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
