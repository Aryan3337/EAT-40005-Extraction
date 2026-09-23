from prompts.loader import load_prompt, load_prompt_template


def test_load_prompt_template_reads_real_file():
    text = load_prompt_template("extraction_broad_v2")
    assert "{passage}" in text
    assert "Garo" in text


def test_load_prompt_fills_in_passage():
    build_prompt = load_prompt("extraction_broad_v2")
    result = build_prompt("Some passage text.")
    assert "Some passage text." in result
    assert "{passage}" not in result


def test_load_prompt_strict_tacit_has_no_leftover_placeholder():
    build_prompt = load_prompt("extraction_strict_tacit_v1")
    result = build_prompt("Example passage.")
    assert "Example passage." in result
    assert "{passage}" not in result


def test_verify_prompt_template_has_expected_placeholders():
    text = load_prompt_template("verify_tacit_evidence_v1")
    for placeholder in ("{source_sentence}", "{subject}", "{predicate}", "{object}"):
        assert placeholder in text
