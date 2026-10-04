from verification.grounding_check import check_grounding


def test_subject_and_object_both_present_not_flagged():
    result = check_grounding("GaroMen", "Trousers", "Garo men wear lungis, genjis, trousers, and shirts.")
    assert result.flagged is False
    assert result.reasons == []


def test_object_not_in_sentence_is_flagged():
    result = check_grounding("GaroCommunity", "BottleGourd", "They enjoy a variety of vegetables such as brinjal.")
    assert result.flagged is True
    assert any("Object" in reason and "BottleGourd" in reason for reason in result.reasons)


def test_subject_not_in_sentence_is_flagged():
    result = check_grounding("FloatingIslandCommunity", "Rice", "The primary food of Garo people is rice.")
    assert result.flagged is True
    assert any("Subject" in reason and "FloatingIslandCommunity" in reason for reason in result.reasons)


def test_empty_sentence_ref_is_flagged():
    # Fail closed: no source sentence means no evidence, so it cannot be
    # considered grounded regardless of what the entity names say.
    result = check_grounding("GaroCommunity", "Rice", "")
    assert result.flagged is True
    assert any("sentence_ref" in reason.lower() for reason in result.reasons)


def test_matching_is_case_insensitive():
    result = check_grounding("GaroMen", "Lungis", "GARO MEN WEAR LUNGIS.")
    assert result.flagged is False


def test_partial_multiword_entity_match_is_flagged():
    # Only "matrilineal" appears in the sentence -- "system" never does.
    # Every word of a multi-word entity must be grounded, not just one.
    result = check_grounding(
        "GaroCommunity", "MatrilinealSystem",
        "The community traditionally follows a matrilineal approach to inheritance.",
    )
    assert result.flagged is True
    assert any("MatrilinealSystem" in reason for reason in result.reasons)


# -- Citation-length bound (added 2026-10-04) ---------------------------------
# A sentence_ref is supposed to be the ONE sentence a triple was read from. On
# the 2026-09-29 garo_1.pdf run, 4 of 17 surviving triples shared a single
# 772-char, five-sentence PARAGRAPH as their citation. Every one of them passed
# entity grounding -- a long enough citation restates so many words that
# grounding becomes trivial to satisfy. Exact-match grounding therefore rewards
# verbose citations, which is the dangerous direction. Bounding the citation
# length closes that off.


def test_paragraph_length_sentence_ref_is_flagged():
    paragraph = (
        "The primary occupation of Garo people is farming, which supports about more "
        "than 85% of the community. However, in the last few decades, They have been "
        "adjusting to new technologies and job opportunities. The result is, many Garos "
        "have had to change their professions to earn sufficient wages. They are "
        "currently seeking employment in public and private offices, garment stores, "
        "beauty parlors, tea gardens, factories, police and military services in Dhaka."
    )
    assert len(paragraph) > 200
    result = check_grounding("GaroCommunity", "garment stores", paragraph)
    assert result.flagged is True


def test_paragraph_is_flagged_even_when_both_entities_are_grounded():
    # The real defect from the 2026-09-29 run: these rows were NOT caught by
    # entity grounding, because both entities genuinely appear in the paragraph.
    # Length is the only signal that separates them from an honest citation.
    paragraph = (
        "They are currently seeking employment in public and private offices, garment "
        "stores, beauty parlors, tea gardens, factories, police and military services "
        "in Dhaka and other urban areas and also a significant number of Garos are "
        "employed in the Bangladesh Civil Service and various other urban occupations."
    )
    assert len(paragraph) > 200
    result = check_grounding("beauty parlors", "tea gardens", paragraph)
    assert result.flagged is True
    assert any(
        "sentence_ref" in reason.lower() or "paragraph" in reason.lower()
        for reason in result.reasons
    )


def test_length_flag_reason_reports_the_actual_and_allowed_lengths():
    paragraph = ("Garo men wear lungis. " * 20).strip()
    result = check_grounding("Garo men", "lungis", paragraph)
    assert result.flagged is True
    reason = "; ".join(result.reasons)
    assert str(len(paragraph)) in reason
    assert "200" in reason


def test_single_long_sentence_within_the_bound_is_not_flagged():
    # 132 chars was the longest citation among the 13 sound survivors of the
    # 2026-09-29 run, so the bound must sit comfortably above that.
    sentence = (
        "Traditional Garo houses are built on raised platforms with a bamboo floor, "
        "walls of split bamboo, and a thatched roof of sun grass."
    )
    assert 100 < len(sentence) <= 200
    result = check_grounding("bamboo floor", "split bamboo", sentence)
    assert result.flagged is False
    assert result.reasons == []


def test_sentence_ref_at_exactly_the_bound_is_not_flagged():
    sentence = "Garo men wear lungis " * 9 + "and shirts to work here."
    sentence = sentence[:200]
    assert len(sentence) == 200
    result = check_grounding("Garo men", "lungis", sentence)
    assert result.flagged is False
