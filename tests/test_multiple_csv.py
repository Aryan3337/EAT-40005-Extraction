"""Multiple-CSV regression checks using fictional evidence only."""
import csv

from rag import KnowledgeGraph, RAGSkeleton, source_response_answer


def write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def research_row():
    return {
        "subject": "Garo people",
        "predicate": "SPEAK_LANGUAGE",
        "object": "Bengali and Garo language",
        "sentence_ref": "Fictional example: Garo people speak Bengali and Garo.",
        "source_type": "research_paper",
        "paper_title": "Fictional research",
        "source_file": "fictional.pdf",
        "page_number": "1",
    }


def community_rows():
    return [
        {
            "subject": f"Community record {index:02d} forest management",
            "predicate": "REPORTED_RESPONSE",
            "object": response,
            "sentence_ref": f"Fictional forest management response: {response}",
            "question": "Have you noticed changes in forest management?",
            "source_type": "community_data",
            "evidence_kind": "narrative",
            "paper_title": f"Community record {index:02d}",
            "source_file": f"fictional-{index}.docx",
            "record_id": str(index),
        }
        for index, response in enumerate(
            ["No.", "Fewer trees.", "Less fruit.", "Smaller forest.",
             "Fewer plants.", "Less shade."],
            start=1,
        )
    ]


def test_single_path_and_list_are_compatible(tmp_path):
    path = write_csv(tmp_path / "research.csv", [research_row()])
    assert KnowledgeGraph(str(path)).triples == KnowledgeGraph([path]).triples


def test_multiple_files_preserve_fields_and_unique_ids(tmp_path):
    first = write_csv(tmp_path / "research.csv", [research_row()])
    second = write_csv(tmp_path / "community.csv", community_rows())
    separate = KnowledgeGraph(first).triples + KnowledgeGraph(second).triples
    combined = KnowledgeGraph([first, second]).triples

    assert len(combined) == 7
    assert len({row["id"] for row in combined}) == 7
    without_ids = lambda rows: [
        {key: value for key, value in row.items() if key != "id"}
        for row in rows
    ]
    assert without_ids(combined) == without_ids(separate)


def test_same_file_is_not_loaded_twice(tmp_path):
    path = write_csv(tmp_path / "research.csv", [research_row()])
    assert len(KnowledgeGraph([str(path), path.resolve()]).triples) == 1


def test_one_index_answers_both_topics(tmp_path):
    first = write_csv(tmp_path / "research.csv", [research_row()])
    second = write_csv(tmp_path / "community.csv", community_rows())
    retriever = RAGSkeleton([first, second])

    language = retriever.query("Which languages do the Garo people speak?", top_k=10)
    assert len(language) == 1
    assert language[0]["source_type"] == "research_paper"

    community = retriever.query(
        "Have you noticed changes in forest management?", top_k=10
    )
    assert len(community) == 6
    answer = source_response_answer(community)
    assert "Community record 01: No." in answer


def test_relevant_community_language_evidence_is_kept(tmp_path):
    row = community_rows()[0]
    row.update(
        subject="Community record 01 Garo language",
        question="Which languages do the Garo people speak?",
        object="Bengali and Garo.",
        sentence_ref="Fictional participant reported Bengali and Garo language.",
    )
    first = write_csv(tmp_path / "research.csv", [research_row()])
    second = write_csv(tmp_path / "community.csv", [row])
    result = RAGSkeleton([first, second]).query(
        "Which languages do the Garo people speak?", top_k=10
    )
    assert {item["source_type"] for item in result} == {
        "research_paper", "community_data"
    }


def test_identity_only_question_keeps_matching_evidence(tmp_path):
    row = research_row()
    row.update(predicate="IS_A", object="Indigenous community")
    path = write_csv(tmp_path / "identity.csv", [row])
    assert RAGSkeleton(path).query("Garo people", top_k=10)
