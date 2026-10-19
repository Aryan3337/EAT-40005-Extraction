from auth_store import AuthStore


class _FakeResult:
    def __init__(self, record):
        self._record = record

    def single(self):
        return self._record


class _FakeSession:
    def __init__(self, records):
        self.records = records if isinstance(records, list) else [records]
        self.calls = []
        self.query = ""
        self.parameters = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def run(self, query, **parameters):
        self.calls.append((query, parameters))
        self.query = query
        self.parameters = parameters
        return _FakeResult(self.records[len(self.calls) - 1])


class _FakeDriver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return self._session


def test_username_is_normalized_and_validated():
    assert AuthStore._normalise_username(" New.User_1 ") == "new.user_1"

    try:
        AuthStore._normalise_username("not a valid username")
    except ValueError as error:
        assert "Username" in str(error)
    else:
        raise AssertionError("Invalid username was accepted")


def test_login_looks_up_username_or_email_and_returns_the_account():
    password = "correct horse battery"
    password_hash = AuthStore._hash_password(password)
    session = _FakeSession(
        {
            "email": "person@example.com",
            "role": "user",
            "password_hash": password_hash,
        }
    )
    store = object.__new__(AuthStore)
    store._driver = _FakeDriver(session)
    store._sessions = {}

    account = store.login(" New.User ", password)

    assert account is not None
    assert account["email"] == "person@example.com"
    assert "u.email" in session.query
    assert "u.username" in session.query
    assert session.parameters == {"identifier": "new.user"}


def test_login_still_accepts_existing_email_accounts():
    password = "correct horse battery"
    password_hash = AuthStore._hash_password(password)
    session = _FakeSession(
        {
            "email": "person@example.com",
            "role": "user",
            "password_hash": password_hash,
        }
    )
    store = object.__new__(AuthStore)
    store._driver = _FakeDriver(session)
    store._sessions = {}

    account = store.login("PERSON@example.com", password)

    assert account is not None
    assert account["email"] == "person@example.com"


def test_register_persists_the_normalized_username(monkeypatch):
    session = _FakeSession(
        [
            None,
            {"email": "person@example.com", "role": "user"},
        ]
    )
    store = object.__new__(AuthStore)
    store._driver = _FakeDriver(session)
    store._sessions = {}
    monkeypatch.setattr(AuthStore, "_hash_password", staticmethod(lambda _: "hash"))

    account = store.register("person@example.com", "a strong password", "New.User")

    assert account["email"] == "person@example.com"
    create_query, parameters = session.calls[1]
    assert "SET u.username = $username" in create_query
    assert parameters["username"] == "new.user"
