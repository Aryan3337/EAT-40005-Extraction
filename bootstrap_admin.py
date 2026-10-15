"""Create or reset an administrator account in the configured Neo4j database."""

import getpass

from auth_store import AuthStore


def main() -> None:
    username = input("Administrator email or username: ").strip()
    password = getpass.getpass("Administrator password: ")
    confirmation = getpass.getpass("Confirm administrator password: ")

    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    store = AuthStore()
    try:
        store.create_admin(username, password)
    finally:
        store.close()
    print(f"Administrator account {username!r} is ready.")


if __name__ == "__main__":
    main()
