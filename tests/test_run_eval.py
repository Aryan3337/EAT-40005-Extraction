import csv

from eval.run_eval import RESULTS_FIELDS, append_result, load_extracted
from eval.scorer import score


def test_load_extracted_reads_subject_predicate_object(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "extraction_number,paper,subject,predicate,object,source_section\n"
        "1,garo_1,GaroCommunity,WEARS,Lungis,Page 3\n",
        encoding="utf-8",
    )
    extracted = load_extracted(str(csv_path))
    assert extracted == [("GaroCommunity", "WEARS", "Lungis")]


def test_load_extracted_works_with_test_extraction_csv_shape(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "page_number,subject,predicate,object,confidence_score\n"
        "3,GaroCommunity,WEARS,Lungis,1.0\n",
        encoding="utf-8",
    )
    extracted = load_extracted(str(csv_path))
    assert extracted == [("GaroCommunity", "WEARS", "Lungis")]


def test_append_result_creates_header_on_first_write(tmp_path):
    results_path = tmp_path / "results.csv"
    report = score([("GaroCommunity", "WEARS", "Lungis")], [("GaroCommunity", "WEARS", "Lungis")], num_pages=1)

    append_result(report, "Test Label", "some.csv", "3", str(results_path))

    with open(results_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == RESULTS_FIELDS
    assert rows[1][1] == "Test Label"
    assert rows[1][2] == "some.csv"
    assert rows[1][3] == "3"


def test_append_result_appends_without_duplicate_header(tmp_path):
    results_path = tmp_path / "results.csv"
    report = score([], [("GaroCommunity", "WEARS", "Lungis")], num_pages=1)

    append_result(report, "First", "a.csv", "3", str(results_path))
    append_result(report, "Second", "b.csv", "3", str(results_path))

    with open(results_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3  # header + 2 data rows
    assert rows[1][1] == "First"
    assert rows[2][1] == "Second"


def test_append_result_leaves_hallucination_rate_blank_when_not_computed(tmp_path):
    results_path = tmp_path / "results.csv"
    report = score([("GaroCommunity", "WEARS", "Lungis")], [("GaroCommunity", "WEARS", "Lungis")], num_pages=1)

    append_result(report, "No PDF given", "some.csv", "3", str(results_path))

    with open(results_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0][-2:] == ["hallucination_rate", "citation_coverage"]
    assert rows[1][-2:] == ["", ""]


def test_append_result_records_real_hallucination_rate_when_given(tmp_path):
    results_path = tmp_path / "results.csv"
    report = score([("GaroCommunity", "WEARS", "Lungis")], [("GaroCommunity", "WEARS", "Lungis")], num_pages=1)

    append_result(report, "With PDF", "some.csv", "3", str(results_path),
                  hallucination_rate=0.25, citation_coverage=0.9)

    with open(results_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[1][-2:] == ["0.25", "0.9"]
