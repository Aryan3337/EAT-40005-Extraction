"""Neo4j-backed account storage for the API authentication endpoints."""

import hashlib
import hmac
import json
import secrets
import uuid
from typing import Dict, Optional

from neo4j import GraphDatabase

from config import PASSWORD, URI, USERNAME


class AuthStore:
    """Stores users in Neo4j and keeps opaque sessions in API memory."""

    def __init__(self) -> None:
        if not URI or not USERNAME or not PASSWORD:
            raise RuntimeError(
                "NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD are required "
                "for authentication."
            )
        self._driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))
        self._sessions: Dict[str, Dict[str, str]] = {}
        with self._driver.session() as session:
            session.run(
                "CREATE CONSTRAINT user_email_unique IF NOT EXISTS "
                "FOR (u:User) REQUIRE u.email IS UNIQUE"
            ).consume()

    def close(self) -> None:
        self._driver.close()

    def register(self, email: str, password: str) -> Dict[str, str]:
        email = self._normalise_email(email)
        self._validate_password(password)
        password_hash = self._hash_password(password)
        with self._driver.session() as session:
            existing = session.run(
                "MATCH (u:User {email: $email}) RETURN u.email AS email",
                email=email,
            ).single()
            if existing is not None:
                raise ValueError("An account already exists.")
            result = session.run(
                "CREATE (u:User {email: $email, password_hash: $password_hash, "
                "role: 'user', created_at: datetime()}) "
                "RETURN u.email AS email, u.role AS role",
                email=email,
                password_hash=password_hash,
            ).single()
        if result is None:
            raise RuntimeError("The account could not be created.")
        return self._start_session(result["email"], result["role"])

    def create_admin(self, username: str, password: str) -> None:
        """Create or replace an administrator account in Neo4j.

        This is intended for the one-time bootstrap command, not a public API
        endpoint. The plaintext password only exists for the duration of this
        call and is stored only as a salted hash.
        """
        username = self._normalise_identifier(username)
        self._validate_password(password)
        with self._driver.session() as session:
            session.run(
                "MERGE (u:User {email: $username}) "
                "ON CREATE SET u.created_at = datetime() "
                "SET u.password_hash = $password_hash, u.role = 'admin'",
                username=username,
                password_hash=self._hash_password(password),
            ).consume()

    def login(self, email: str, password: str) -> Optional[Dict[str, str]]:
        email = self._normalise_identifier(email)
        with self._driver.session() as session:
            result = session.run(
                "MATCH (u:User {email: $email}) "
                "RETURN u.email AS email, u.role AS role, "
                "u.password_hash AS password_hash",
                email=email,
            ).single()
        if result is None or not self._verify_password(
            password, result["password_hash"]
        ):
            return None
        return self._start_session(result["email"], result["role"])

    def session(self, token: str) -> Optional[Dict[str, str]]:
        return self._sessions.get(token)

    def users(self) -> list[Dict[str, object]]:
        with self._driver.session() as session:
            records = session.run(
                "MATCH (u:User) "
                "CALL (u) { "
                "OPTIONAL MATCH (u)-[:LEFT_FEEDBACK]->(f:Feedback) "
                "RETURN count(f) AS feedback_count "
                "} "
                "CALL (u) { "
                "OPTIONAL MATCH (u)-[:HAS_CONVERSATION]->(c:Conversation) "
                "RETURN count(c) AS conversation_count "
                "} "
                "CALL (u) { "
                "OPTIONAL MATCH (u)-[:HAS_CONVERSATION]->(:Conversation)"
                "-[:HAS_MESSAGE]->(m:ChatMessage) "
                "RETURN count(m) AS message_count "
                "} "
                "RETURN u.email AS email, u.role AS role, "
                "toString(u.created_at) AS created_at, "
                "feedback_count, conversation_count, message_count "
                "ORDER BY u.created_at DESC"
            )
            return [dict(record) for record in records]

    def update_user(
        self,
        current_email: str,
        new_email: str,
        role: str,
        password: str = "",
    ) -> None:
        current_email = self._normalise_identifier(current_email)
        new_email = self._normalise_identifier(new_email)
        if role not in {"user", "admin"}:
            raise ValueError("Role must be user or admin.")
        if password:
            self._validate_password(password)
        with self._driver.session() as session:
            if current_email != new_email:
                existing = session.run(
                    "MATCH (u:User {email: $email}) RETURN u.email AS email",
                    email=new_email,
                ).single()
                if existing is not None:
                    raise ValueError("An account already exists with that identifier.")
            user = session.run(
                "MATCH (u:User {email: $email}) RETURN u.role AS role",
                email=current_email,
            ).single()
            if user is None:
                raise ValueError("User account not found.")
            if user["role"] == "admin" and role != "admin":
                remaining = session.run(
                    "MATCH (u:User {role: 'admin'}) RETURN count(u) AS count"
                ).single()
                if remaining is not None and remaining["count"] <= 1:
                    raise ValueError("At least one administrator account is required.")
            password_clause = ", u.password_hash = $password_hash" if password else ""
            session.run(
                f"MATCH (u:User {{email: $current_email}}) "
                f"SET u.email = $new_email, u.role = $role{password_clause}",
                current_email=current_email,
                new_email=new_email,
                role=role,
                password_hash=self._hash_password(password) if password else None,
            ).consume()
            for token, session_user in list(self._sessions.items()):
                if session_user["email"] == current_email:
                    del self._sessions[token]

    def delete_user(self, email: str) -> None:
        email = self._normalise_identifier(email)
        with self._driver.session() as session:
            user = session.run(
                "MATCH (u:User {email: $email}) RETURN u.role AS role",
                email=email,
            ).single()
            if user is None:
                raise ValueError("User account not found.")
            if user["role"] == "admin":
                raise ValueError("Administrator accounts cannot be deleted here.")
            session.run(
                "MATCH (u:User {email: $email}) DETACH DELETE u",
                email=email,
            ).consume()
        for token, session_user in list(self._sessions.items()):
            if session_user["email"] == email:
                del self._sessions[token]

    def save_feedback(
        self,
        user_email: str,
        conversation_id: str,
        response_text: str,
        rating: str,
        comment: str,
    ) -> None:
        if rating not in {"helpful", "notHelpful"}:
            raise ValueError("feedback must be helpful or notHelpful.")
        if not conversation_id or not response_text:
            raise ValueError("A conversation and response are required.")
        if len(comment) > 2_000:
            raise ValueError("Feedback comments must be 2,000 characters or fewer.")
        with self._driver.session() as session:
            session.run(
                "MATCH (u:User {email: $email}) "
                "CREATE (u)-[:LEFT_FEEDBACK]->(f:Feedback {"
                "id: $id, conversation_id: $conversation_id, "
                "response_text: $response_text, rating: $rating, "
                "comment: $comment, created_at: datetime()})",
                email=user_email,
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                response_text=response_text,
                rating=rating,
                comment=comment,
            ).consume()

    def feedback_for_user(self, user_email: str) -> list[Dict[str, str]]:
        with self._driver.session() as session:
            records = session.run(
                "MATCH (:User {email: $email})-[:LEFT_FEEDBACK]->(f:Feedback) "
                "RETURN f.id AS id, f.conversation_id AS conversation_id, "
                "f.response_text AS response_text, f.rating AS rating, "
                "f.comment AS comment, toString(f.created_at) AS created_at "
                "ORDER BY f.created_at DESC",
                email=user_email,
            )
            return [dict(record) for record in records]

    def delete_feedback(self, user_email: str) -> None:
        with self._driver.session() as session:
            session.run(
                "MATCH (:User {email: $email})-[:LEFT_FEEDBACK]->(f:Feedback) "
                "DETACH DELETE f",
                email=user_email,
            ).consume()

    def save_history(self, user_email: str, conversations: list[Dict]) -> None:
        with self._driver.session() as session:
            ids = [str(item.get("id", "")) for item in conversations]
            session.run(
                "MATCH (:User {email: $email})-[:HAS_CONVERSATION]->(c:Conversation) "
                "WHERE NOT c.id IN $ids DETACH DELETE c",
                email=user_email,
                ids=ids,
            ).consume()
            for conversation in conversations:
                conversation_id = str(conversation.get("id", "")).strip()
                if not conversation_id:
                    continue
                session.run(
                    "MATCH (u:User {email: $email}) "
                    "MERGE (u)-[:HAS_CONVERSATION]->"
                    "(c:Conversation {id: $conversation_id}) "
                    "SET c.title = $title, c.updated_at = $updated_at "
                    "WITH c "
                    "OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(old) "
                    "DETACH DELETE old",
                    email=user_email,
                    conversation_id=conversation_id,
                    title=str(conversation.get("title", "New conversation")),
                    updated_at=str(conversation.get("updatedAt", "")),
                ).consume()
                messages = conversation.get("messages", [])
                for index, message in enumerate(messages):
                    session.run(
                        "MATCH (:User {email: $email})-[:HAS_CONVERSATION]->"
                        "(c:Conversation {id: $conversation_id}) "
                        "CREATE (c)-[:HAS_MESSAGE]->"
                        "(m:ChatMessage {position: $position, payload: $payload})",
                        email=user_email,
                        conversation_id=conversation_id,
                        position=index,
                        payload=json.dumps(message),
                    ).consume()

    def history_for_user(self, user_email: str) -> list[Dict]:
        with self._driver.session() as session:
            records = session.run(
                "MATCH (:User {email: $email})-[:HAS_CONVERSATION]->(c:Conversation) "
                "OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:ChatMessage) "
                "RETURN c.id AS id, c.title AS title, c.updated_at AS updated_at, "
                "m.position AS position, m.payload AS payload "
                "ORDER BY c.updated_at DESC, m.position ASC",
                email=user_email,
            )
            conversations: Dict[str, Dict] = {}
            for record in records:
                conversation_id = record["id"]
                conversation = conversations.setdefault(
                    conversation_id,
                    {
                        "id": conversation_id,
                        "title": record["title"] or "New conversation",
                        "updatedAt": record["updated_at"] or "",
                        "messages": [],
                    },
                )
                if record["payload"]:
                    conversation["messages"].append(json.loads(record["payload"]))
            return list(conversations.values())

    def delete_history(self, user_email: str, conversation_id: str) -> None:
        with self._driver.session() as session:
            session.run(
                "MATCH (:User {email: $email})-[:HAS_CONVERSATION]->"
                "(c:Conversation {id: $conversation_id}) DETACH DELETE c",
                email=user_email,
                conversation_id=conversation_id,
            ).consume()

    @staticmethod
    def _normalise_email(email: str) -> str:
        normalised = email.strip().lower()
        if len(normalised) < 3 or len(normalised) > 254 or "@" not in normalised:
            raise ValueError("Enter a valid email address.")
        return normalised

    @staticmethod
    def _normalise_identifier(identifier: str) -> str:
        normalised = identifier.strip().lower()
        if not normalised or len(normalised) > 254:
            raise ValueError("Enter your username or email address.")
        return normalised


    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if len(password) > 256:
            raise ValueError("Password is too long.")

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, 310_000
        )
        return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"

    @staticmethod
    def _verify_password(password: str, encoded: str) -> bool:
        try:
            algorithm, rounds, salt_hex, digest_hex = encoded.split("$")
            if algorithm != "pbkdf2_sha256":
                return False
            expected = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode(),
                bytes.fromhex(salt_hex),
                int(rounds),
            )
            return hmac.compare_digest(expected.hex(), digest_hex)
        except (AttributeError, ValueError):
            return False

    def _start_session(self, email: str, role: str) -> Dict[str, str]:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {"token": token, "email": email, "role": role}
        return self._sessions[token]
