import pytest

from auth_store import AuthStore


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        (" Person.Name+tag@Example.COM ", "person.name+tag@example.com"),
        ("person@localhost", None),
        ("person..name@example.com", None),
        ("@example.com", None),
    ],
)
def test_email_normalization_and_validation(email, expected):
    if expected is None:
        with pytest.raises(ValueError, match="valid email"):
            AuthStore._normalise_email(email)
    else:
        assert AuthStore._normalise_email(email) == expected


@pytest.mark.parametrize(
    ("username", "expected"),
    [
        ("New.User_1", "new.user_1"),
        ("ab", None),
        ("not valid", None),
        ("x" * 31, None),
    ],
)
def test_username_normalization_and_validation(username, expected):
    if expected is None:
        with pytest.raises(ValueError, match="Username"):
            AuthStore._normalise_username(username)
    else:
        assert AuthStore._normalise_username(username) == expected


def test_phone_country_code_and_number_are_normalized():
    assert AuthStore._normalise_phone_country_code(" +61 ") == "+61"
    assert AuthStore._normalise_phone_number("(0412) 345-678") == "0412345678"


@pytest.mark.parametrize(
    ("normalizer", "value"),
    [
        (AuthStore._normalise_phone_country_code, "61"),
        (AuthStore._normalise_phone_country_code, "+0"),
        (AuthStore._normalise_phone_number, "12"),
        (AuthStore._normalise_phone_number, "1" * 15),
    ],
)
def test_invalid_phone_details_are_rejected(normalizer, value):
    with pytest.raises(ValueError):
        normalizer(value)
