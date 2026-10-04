from verification.quote_check import check_quote_genuine


PAGE_TEXT = (
    "Garo men wear lungis, genjis, trousers, and shirts. Many of them prefer "
    "to wear lungis and also wrap a colorful thin towel, similar to a gamcha "
    "or dhuti, around their lower body."
)


def test_verbatim_quote_is_not_flagged():
    result = check_quote_genuine(
        "<Garo men wear lungis, genjis, trousers, and shirts.>", PAGE_TEXT
    )
    assert result.flagged is False
    assert result.reasons == []


def test_fabricated_quote_is_flagged():
    result = check_quote_genuine(
        "<The passage mentions Garo men wearing formal suits to work.>", PAGE_TEXT
    )
    assert result.flagged is True
    assert any("not found verbatim" in reason for reason in result.reasons)


def test_matching_is_case_and_punctuation_insensitive():
    result = check_quote_genuine(
        '"GARO MEN WEAR LUNGIS, GENJIS, TROUSERS, AND SHIRTS."', PAGE_TEXT
    )
    assert result.flagged is False


def test_curly_quotes_and_dashes_are_normalized():
    page = "The Garo’s clothing — lungis and shirts — is common."
    result = check_quote_genuine("<The Garo's clothing - lungis and shirts - is common.>", page)
    assert result.flagged is False


def test_multiple_spans_all_must_be_genuine():
    ref = (
        "<Garo men wear lungis, genjis, trousers, and shirts.>\n"
        "// SENTENCE REF: <This sentence was never written by anyone.>"
    )
    result = check_quote_genuine(ref, PAGE_TEXT)
    assert result.flagged is True
    assert any("This sentence was never written" in reason for reason in result.reasons)


def test_empty_sentence_ref_is_flagged():
    result = check_quote_genuine("", PAGE_TEXT)
    assert result.flagged is True
    assert any("sentence_ref" in reason.lower() for reason in result.reasons)


def test_sentence_ref_with_no_quoted_span_is_flagged():
    result = check_quote_genuine("no angle brackets or quotes here at all", PAGE_TEXT)
    assert result.flagged is True


def test_ellipsis_truncated_genuine_quote_is_not_flagged():
    # A real extraction habit: the model truncates a long sentence with a
    # trailing "..." instead of quoting it in full. The part before the
    # ellipsis is still a genuine verbatim prefix and should pass.
    result = check_quote_genuine(
        '"Garo men wear lungis, genjis, trousers..."', PAGE_TEXT
    )
    assert result.flagged is False


def test_ellipsis_spliced_fabrication_is_still_flagged():
    # Both sides of the ellipsis must independently be genuine -- splicing a
    # real fragment onto an invented one must not slip through.
    result = check_quote_genuine(
        '"Garo men wear lungis...and also formal business suits to the office."',
        PAGE_TEXT,
    )
    assert result.flagged is True
