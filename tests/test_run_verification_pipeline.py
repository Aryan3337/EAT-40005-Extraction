import csv

from run_verification_pipeline import run


def test_run_verification_pipeline_writes_expected_outputs(tmp_path):
    csv_path = tmp_path / "sample.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["GaroCommunity", "WEARS", "Lungis", "Garo men wear lungis."])
        writer.writerow(["PioneeringGaroScholarThe", "WROTE", "Book", "A scholar wrote a book."])

    summary = run(str(csv_path), run_wellformed=True)

    # A flagged row is excluded from refined and recorded in its own gate's
    # audit file; only the clean row reaches refined.
    assert summary == {
        "refined": 1,
        "wellformedness_flags": 1,
        "grounding_flags": 0,
        "quote_flags": 0,
    }

    assert (tmp_path / "sample_refined.csv").exists()
    assert (tmp_path / "sample_wellformedness_flags.csv").exists()

    with open(tmp_path / "sample_wellformedness_flags.csv", newline="", encoding="utf-8") as f:
        flagged_rows = list(csv.DictReader(f))
    assert flagged_rows[0]["subject"] == "PioneeringGaroScholarThe"
    assert "dangling word" in flagged_rows[0]["flag_reason"]


def test_run_verification_pipeline_hard_gates_flagged_rows(tmp_path):
    csv_path = tmp_path / "sample2.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["PioneeringGaroScholarThe", "WROTE", "Book", "A scholar wrote a book."])

    summary = run(str(csv_path), run_wellformed=True)

    # The deterministic checks are a hard gate on refined -- no human
    # downstream to catch a flagged row that slipped through, so it must
    # never reach refined.
    assert summary["refined"] == 0
    assert summary["wellformedness_flags"] == 1


def test_run_verification_pipeline_unflagged_row_still_reaches_refined(tmp_path):
    csv_path = tmp_path / "sample2b.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["GaroCommunity", "WEARS", "Lungis", "Garo men wear lungis."])

    summary = run(str(csv_path), run_wellformed=True)

    assert summary["refined"] == 1
    assert summary["wellformedness_flags"] == 0


def test_run_verification_pipeline_hard_gates_ungrounded_rows(tmp_path):
    csv_path = tmp_path / "sample6.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        # "BottleGourd" never appears in the sentence -- fabricated specific.
        writer.writerow(["GaroCommunity", "HAS_INGREDIENT", "BottleGourd", "They enjoy a variety of vegetables."])
        writer.writerow(["GaroMen", "WEARS", "Lungis", "Garo men wear lungis."])

    summary = run(str(csv_path), run_wellformed=False, run_grounding=True)

    assert summary["refined"] == 1
    assert summary["grounding_flags"] == 1
    assert (tmp_path / "sample6_grounding_flags.csv").exists()


def test_run_verification_pipeline_grounding_check_off_by_default(tmp_path):
    csv_path = tmp_path / "sample7.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["GaroCommunity", "HAS_INGREDIENT", "BottleGourd", "They enjoy a variety of vegetables."])

    summary = run(str(csv_path), run_wellformed=False)

    assert summary["refined"] == 1
    assert summary["grounding_flags"] == 0


def test_run_verification_pipeline_hard_gates_fabricated_quotes(tmp_path):
    csv_path = tmp_path / "sample8.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["page_number", "subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["3", "GaroMen", "WEARS", "Lungis", "<Garo men wear lungis.>"])
        # This quote is entirely invented -- not present on page 3 at all.
        writer.writerow(["3", "Fishman", "USED_IN", "Research", "<The passage mentions Fishman's approach.>"])

    page_texts = {3: "Garo men wear lungis."}
    summary = run(
        str(csv_path), run_wellformed=False,
        run_quote_check=True, page_texts=page_texts,
    )

    assert summary["refined"] == 1
    assert summary["quote_flags"] == 1
    assert (tmp_path / "sample8_quote_flags.csv").exists()


def test_run_verification_pipeline_quote_check_off_by_default(tmp_path):
    csv_path = tmp_path / "sample9.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["page_number", "subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["3", "Fishman", "USED_IN", "Research", "<a fabricated quote>"])

    summary = run(str(csv_path), run_wellformed=False)

    assert summary["refined"] == 1
    assert summary["quote_flags"] == 0


def test_run_verification_pipeline_quote_check_requires_page_texts(tmp_path):
    csv_path = tmp_path / "sample10.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["page_number", "subject", "predicate", "object", "sentence_ref"])
        writer.writerow(["3", "GaroMen", "WEARS", "Lungis", "<Garo men wear lungis.>"])

    try:
        run(str(csv_path), run_wellformed=False, run_quote_check=True)
        assert False, "expected a ValueError"
    except ValueError as e:
        assert "page_texts" in str(e)


def test_quote_check_derives_page_number_from_source_section(tmp_path):
    # Every other quote-check test here hand-writes a page_number column, but
    # kg_extractor.py never emits one: a real output/<paper>_kg.csv carries
    # source_section="Page 3" instead. main.py derives page_number from it
    # before gating; this pipeline has to do the same, or the quote gate
    # fails closed on every row and refined comes out empty. Measured on the
    # real garo_2 corpus: 0 kept here against main.py's 24.
    csv_path = tmp_path / "from_extractor.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["subject", "predicate", "object", "source_section", "sentence_ref"])
        writer.writerow(["GaroMen", "WEARS", "Lungis", "Page 3", "<Garo men wear lungis.>"])

    summary = run(
        str(csv_path), run_wellformed=False,
        run_quote_check=True, page_texts={3: "Garo men wear lungis."},
    )

    assert summary["refined"] == 1
    assert summary["quote_flags"] == 0


def test_an_explicit_page_number_column_still_wins(tmp_path):
    # Deriving must not clobber a page_number a caller already supplied --
    # run_page_pipeline.py writes one directly.
    csv_path = tmp_path / "both_columns.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["page_number", "subject", "predicate", "object", "source_section", "sentence_ref"])
        writer.writerow(["3", "GaroMen", "WEARS", "Lungis", "Page 99", "<Garo men wear lungis.>"])

    summary = run(
        str(csv_path), run_wellformed=False,
        run_quote_check=True, page_texts={3: "Garo men wear lungis."},
    )

    assert summary["refined"] == 1
