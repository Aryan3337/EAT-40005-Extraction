"""Covers AuthStore's input normalisers.

Scope note, because this file misled a reader once already. It was written
against 658ec35, which registered an account from five fields (username,
email, phone country code, phone number, password). 93c85bf reverted that
the same day -- register() takes email and password, and the username and
phone validators were deleted -- but left this file untouched. The stale
reference to AuthStore._normalise_phone_country_code sat inside a
@pytest.mark.parametrize argument, so it was evaluated at import and took
down collection for the WHOLE suite, not just this module.

So: only test normalisers that exist. The two that do are _normalise_email
(registration and email changes) and _normalise_identifier (login).

What this file deliberately does NOT cover, because it is not AuthStore's
bug to fix: the Flutter client still posts username, phone_country_code
and phone_number (auth_service.dart:122) and rag.py's _handle_auth reads
only email and password, so all three are silently discarded. Recorded in
KNOWN_LIMITATIONS.md.
"""

import pytest

from auth_store import AuthStore


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        # Surrounding space and mixed case are normalised away, and a
        # +tag local part is legitimate -- do not "fix" it into a reject.
        (" Person.Name+tag@Example.COM ", "person.name+tag@example.com"),
        # No dotted TLD. A bare host is unroutable for mail.
        ("person@localhost", None),
        # Consecutive dots in the local part.
        ("person..name@example.com", None),
        # Empty local part. This one is the reason the validator is strict
        # rather than `"@" in value`: that check accepts this address.
        ("@example.com", None),
    ],
)
def test_email_normalization_and_validation(email, expected):
    if expected is None:
        with pytest.raises(ValueError, match="valid email"):
            AuthStore._normalise_email(email)
    else:
        assert AuthStore._normalise_email(email) == expected


def test_overlong_email_is_rejected():
    """254 is the RFC ceiling on a whole address."""
    too_long = "a" * 250 + "@example.com"
    with pytest.raises(ValueError, match="valid email"):
        AuthStore._normalise_email(too_long)


def test_overlong_local_part_is_rejected():
    """64 is the RFC ceiling on the local part, independent of the total."""
    with pytest.raises(ValueError, match="valid email"):
        AuthStore._normalise_email("a" * 65 + "@example.com")


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("  Someone@Example.COM ", "someone@example.com"),
        ("SomeUser", "someuser"),
    ],
)
def test_identifier_is_trimmed_and_lowercased(identifier, expected):
    """login() takes either a username or an email, so _normalise_identifier
    is deliberately looser than _normalise_email -- it only trims, lowercases
    and bounds the length. It must not start rejecting non-email input."""
    assert AuthStore._normalise_identifier(identifier) == expected


@pytest.mark.parametrize("identifier", ["", "   ", "x" * 255])
def test_empty_or_overlong_identifier_is_rejected(identifier):
    with pytest.raises(ValueError, match="username or email"):
        AuthStore._normalise_identifier(identifier)
