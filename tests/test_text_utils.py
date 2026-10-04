from verification.text_utils import split_camel_case


def test_simple_camel_case():
    assert split_camel_case("GaroCommunity") == ["garo", "community"]


def test_four_word_camel_case():
    assert split_camel_case("PioneeringGaroScholarThe") == [
        "pioneering", "garo", "scholar", "the",
    ]


def test_snake_case_passthrough():
    assert split_camel_case("already_lower") == ["already", "lower"]


def test_empty_string():
    assert split_camel_case("") == []


def test_single_word():
    assert split_camel_case("Lungis") == ["lungis"]
