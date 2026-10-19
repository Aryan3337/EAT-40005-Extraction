"""Neo4j-backed account storage for the API authentication endpoints."""

import hashlib
import hmac
import json
import secrets
import uuid
from typing import Any, Dict, List, Optional

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
            session.run(
                "CREATE CONSTRAINT user_username_unique IF NOT EXISTS "
                "FOR (u:User) REQUIRE u.username IS UNIQUE"
            ).consume()

    def close(self) -> None:
        self._driver.close()

    def register(
        self,
        email: str,
        password: str,
        username: Optional[str] = None,
    ) -> Dict[str, str]:
        email = self._normalise_email(email)
        username = (
            self._normalise_username(username) if username is not None else None
        )
        self._validate_password(password)
        password_hash = self._hash_password(password)
        with self._driver.session() as session:
            existing = session.run(
                "MATCH (u:User) "
                "WHERE u.email = $email OR u.username = $email "
                "OR ($username IS NOT NULL AND "
                "(u.username = $username OR u.email = $username)) "
                "RETURN u.email AS email",
                email=email,
                username=username,
            ).single()
            if existing is not None:
                raise ValueError("An account already exists.")
            result = session.run(
                "CREATE (u:User {email: $email, password_hash: $password_hash, "
                "role: 'user', created_at: datetime()}) "
                "SET u.username = $username "
                "RETURN u.email AS email, u.role AS role",
                email=email,
                username=username,
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
        identifier = self._normalise_identifier(email)
        with self._driver.session() as session:
            result = session.run(
                "MATCH (u:User) "
                "WHERE toLower(u.email) = $identifier "
                "OR toLower(coalesce(u.username, '')) = $identifier "
                "RETURN u.email AS email, u.role AS role, "
                "u.password_hash AS password_hash",
                identifier=identifier,
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
        triple_ids: Optional[list[str]] = None,
    ) -> None:
        if rating not in {"helpful", "notHelpful"}:
            raise ValueError("feedback must be helpful or notHelpful.")
        if not conversation_id or not response_text:
            raise ValueError("A conversation and response are required.")
        if len(comment) > 2_000:
            raise ValueError("Feedback comments must be 2,000 characters or fewer.")
        # Non-string or blank entries are dropped rather than rejecting the
        # whole request -- the id list is supporting evidence for review,
        # not something the person submitting feedback can get wrong.
        clean_triple_ids = [
            str(item).strip()
            for item in (triple_ids or [])
            if str(item or "").strip()
        ]
        with self._driver.session() as session:
            session.run(
                "MATCH (u:User {email: $email}) "
                "CREATE (u)-[:LEFT_FEEDBACK]->(f:Feedback {"
                "id: $id, conversation_id: $conversation_id, "
                "response_text: $response_text, rating: $rating, "
                "comment: $comment, triple_ids: $triple_ids, "
                "status: 'pending', created_at: datetime()})",
                email=user_email,
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                response_text=response_text,
                rating=rating,
                comment=comment,
                triple_ids=clean_triple_ids,
            ).consume()

    # Fields shared by feedback_for_user and all_feedback's RETURN clauses,
    # kept in one place so the two can't silently drift apart.
    _FEEDBACK_FIELDS = (
        "f.id AS id, f.conversation_id AS conversation_id, "
        "f.response_text AS response_text, f.rating AS rating, "
        "f.comment AS comment, coalesce(f.triple_ids, []) AS triple_ids, "
        "coalesce(f.status, 'pending') AS status, "
        "coalesce(f.review_action, '') AS review_action, "
        "coalesce(f.reviewed_by, '') AS reviewed_by, "
        "toString(f.reviewed_at) AS reviewed_at, "
        "coalesce(f.review_note, '') AS review_note, "
        "toString(f.created_at) AS created_at"
    )

    def feedback_for_user(self, user_email: str) -> list[Dict[str, Any]]:
        with self._driver.session() as session:
            records = session.run(
                "MATCH (:User {email: $email})-[:LEFT_FEEDBACK]->(f:Feedback) "
                f"RETURN {self._FEEDBACK_FIELDS} "
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

    def delete_feedback_item(self, user_email: str, feedback_id: str) -> None:
        """Deletes one feedback record, scoped to its owner.

        The MATCH requires BOTH the id and the owning user's email, so a
        person can never delete another user's feedback by guessing or
        reusing an id -- there is no separate ownership check to forget.
        """
        if not feedback_id:
            raise ValueError("A feedback id is required.")
        with self._driver.session() as session:
            result = session.run(
                "MATCH (:User {email: $email})-[:LEFT_FEEDBACK]->(f:Feedback {id: $id}) "
                "DETACH DELETE f RETURN count(f) AS deleted",
                email=user_email,
                id=feedback_id,
            )
            if result.single()["deleted"] == 0:
                raise ValueError("No feedback with that id for this account.")

    def all_feedback(self, status: Optional[str] = None) -> list[Dict[str, Any]]:
        """Every user's feedback, for the admin review queue.

        Optionally filtered to one status ("pending" or "reviewed"). Each
        row's triple_ids are resolved back into readable subject/predicate/
        object text under "triples", so a reviewer can see what the flagged
        answer actually cited without a separate lookup. A triple already
        archived since the feedback was left is still included (and marked
        archived) -- a reviewer checking a past decision needs to see what
        it was, not have it silently vanish.
        """
        with self._driver.session() as session:
            if status:
                records = session.run(
                    "MATCH (u:User)-[:LEFT_FEEDBACK]->(f:Feedback) "
                    "WHERE coalesce(f.status, 'pending') = $status "
                    f"RETURN u.email AS user_email, {self._FEEDBACK_FIELDS} "
                    "ORDER BY f.created_at DESC",
                    status=status,
                )
            else:
                records = session.run(
                    "MATCH (u:User)-[:LEFT_FEEDBACK]->(f:Feedback) "
                    f"RETURN u.email AS user_email, {self._FEEDBACK_FIELDS} "
                    "ORDER BY f.created_at DESC"
                )
            rows = [dict(record) for record in records]

        # One batched lookup for every triple id across every row, rather
        # than one query per row -- see Neo4jRAGSkeleton.query's own
        # comments on why a full scan is fine at this project's scale, but
        # there is no reason to pay for it N times over here regardless.
        all_ids = sorted({
            triple_id
            for row in rows
            for triple_id in (row.get("triple_ids") or [])
            if not str(triple_id).startswith("csv:")
        })
        triples_by_id: Dict[str, Dict[str, Any]] = {}
        if all_ids:
            with self._driver.session() as session:
                records = session.run(
                    "MATCH (s)-[r]->(o) WHERE elementId(r) IN $ids "
                    "RETURN elementId(r) AS id, s.name AS subject, "
                    "type(r) AS predicate, o.name AS object, "
                    "coalesce(r.archived, false) AS archived",
                    ids=all_ids,
                )
                triples_by_id = {record["id"]: dict(record) for record in records}

        for row in rows:
            row["triples"] = [
                triples_by_id[triple_id]
                for triple_id in (row.get("triple_ids") or [])
                if triple_id in triples_by_id
            ]
        return rows

    def review_feedback(
        self,
        feedback_id: str,
        *,
        admin_email: str,
        action: str,
        note: str = "",
        archive_triples: bool = False,
        archive_triple_ids: Optional[List[str]] = None,
        correction: Optional[Dict[str, str]] = None,
    ) -> None:
        """Records an admin's verdict on one feedback record (FB-5's
        provenance: who, when, why) and, only on an "approved" verdict,
        optionally changes the graph (FB-6).

        "approved" means the admin agrees the flagged evidence is actually
        wrong; "rejected" means they looked at it and disagree -- the
        feedback is dismissed and the graph is never touched.

        Which triples get archived is the admin's explicit choice:
        archive_triple_ids names the exact triples (each must be one this
        feedback was attached to). archive_triples=True with no ids is the
        older "archive everything it was attached to" behaviour and is kept
        for API compatibility; the app no longer sends it.

        Everything is validated, and any graph change applied, BEFORE the
        feedback is marked reviewed. If a correction or archive cannot be
        applied the feedback stays pending and nothing is recorded as done.
        """
        if action not in {"approved", "rejected"}:
            raise ValueError("action must be 'approved' or 'rejected'.")
        if len(note) > 2_000:
            raise ValueError("Review notes must be 2,000 characters or fewer.")
        if not feedback_id:
            raise ValueError("A feedback id is required.")
        if correction is not None:
            if action != "approved":
                raise ValueError("A correction can only accompany an approval.")
            correction = self._clean_correction(correction)

        # 1. Read only: what was this feedback attached to?
        with self._driver.session() as session:
            record = session.run(
                "MATCH (:User)-[:LEFT_FEEDBACK]->(f:Feedback {id: $id}) "
                "RETURN coalesce(f.triple_ids, []) AS triple_ids",
                id=feedback_id,
            ).single()
        if record is None:
            raise ValueError("No feedback with that id.")
        triple_ids = record["triple_ids"] or []

        # 2. Decide what to change and validate it, still without writing.
        to_archive: List[str] = []
        if action == "approved" and correction is None:
            if archive_triple_ids is not None:
                to_archive = list(dict.fromkeys(
                    str(tid).strip() for tid in archive_triple_ids if str(tid).strip()
                ))
                unknown = [tid for tid in to_archive if tid not in triple_ids]
                if unknown:
                    raise ValueError(
                        "Some triples to archive were not part of this feedback."
                    )
            elif archive_triples:
                to_archive = list(triple_ids)
        if correction is not None and correction["triple_id"] not in triple_ids:
            raise ValueError(
                "That triple was not part of this feedback, so it "
                "cannot be corrected from it."
            )

        # 3. Apply the graph change. A failure raises here, so the feedback
        #    below is not marked reviewed.
        if correction is not None:
            self._apply_correction(correction, admin_email, note)
        elif to_archive:
            self._archive_triples(to_archive, feedback_id, admin_email, note)

        # 4. Only now record the verdict and provenance.
        with self._driver.session() as session:
            session.run(
                "MATCH (:User)-[:LEFT_FEEDBACK]->(f:Feedback {id: $id}) "
                "SET f.status = 'reviewed', f.review_action = $action, "
                "f.reviewed_by = $admin_email, f.reviewed_at = datetime(), "
                "f.review_note = $note",
                id=feedback_id,
                action=action,
                admin_email=admin_email,
                note=note,
            ).consume()

    def _archive_triples(
        self, ids: List[str], feedback_id: str, admin_email: str, note: str
    ) -> None:
        """Flags triples as archived (never deletes). Already-archived
        triples are left alone so their original archive provenance stays."""
        csv_ids = [tid for tid in ids if str(tid).startswith("csv:")]
        graph_ids = [tid for tid in ids if not str(tid).startswith("csv:")]
        if csv_ids:
            # See the 'id' comment in KnowledgeGraph._load_csv: a CSV-backed
            # triple has nowhere persistent to record an archive flag.
            print(
                f"Feedback {feedback_id}: {len(csv_ids)} CSV-sourced triple(s) "
                "flagged for archiving were skipped -- only Neo4j-backed "
                "triples can be archived."
            )
        if not graph_ids:
            return
        with self._driver.session() as session:
            session.run(
                "MATCH ()-[r]->() WHERE elementId(r) IN $ids "
                "AND coalesce(r.archived, false) = false "
                "SET r.archived = true, r.archived_at = datetime(), "
                "r.archived_by = $admin_email, r.archive_reason = $note",
                ids=graph_ids,
                admin_email=admin_email,
                note=note,
            ).consume()

    @staticmethod
    def _clean_correction(correction: Dict[str, str]) -> Dict[str, str]:
        import re

        cleaned = {k: str(correction.get(k, "")).strip() for k in
                   ("triple_id", "subject", "predicate", "object")}
        if not all(cleaned.values()):
            raise ValueError(
                "A correction needs triple_id, subject, predicate and object."
            )
        if cleaned["triple_id"].startswith("csv:"):
            raise ValueError("CSV-sourced triples cannot be corrected.")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", cleaned["predicate"]):
            raise ValueError(
                "Predicate must be letters, digits and underscores only."
            )
        for key in ("subject", "object"):
            if len(cleaned[key]) > 300:
                raise ValueError(f"{key} is too long.")
        return cleaned

    def _apply_correction(
        self, correction: Dict[str, str], admin_email: str, note: str
    ) -> None:
        """Replaces a wrong triple with a corrected S/P/O. The old
        relationship is archived (not deleted) and the new one records where
        it came from, so the change is traceable and reversible."""
        predicate = correction["predicate"]  # validated as a plain identifier
        with self._driver.session() as session:
            result = session.run(
                "MATCH ()-[old]->() WHERE elementId(old) = $id "
                "MERGE (s:Entity {name: $subject}) "
                "MERGE (o:Entity {name: $object}) "
                f"CREATE (s)-[n:`{predicate}`]->(o) "
                "SET n = properties(old) "
                "SET n.archived = false, n.corrected_from = $id, "
                "n.corrected_by = $admin_email, n.corrected_at = datetime() "
                "REMOVE n.archived_at, n.archived_by, n.archive_reason "
                "SET old.archived = true, old.archived_at = datetime(), "
                "old.archived_by = $admin_email, "
                "old.archive_reason = $reason "
                "RETURN count(n) AS created",
                id=correction["triple_id"],
                subject=correction["subject"],
                object=correction["object"],
                admin_email=admin_email,
                reason=note or "corrected from feedback",
            )
            row = result.single()
            if row is None or not row["created"]:
                raise ValueError("That triple no longer exists.")

    def feedback_stats(self) -> Dict[str, Any]:
        """Aggregate counts for the admin feedback dashboard."""
        with self._driver.session() as session:
            totals = session.run(
                "MATCH (:User)-[:LEFT_FEEDBACK]->(f:Feedback) "
                "RETURN count(f) AS total, "
                "sum(CASE WHEN f.rating = 'helpful' THEN 1 ELSE 0 END) AS helpful, "
                "sum(CASE WHEN f.rating = 'notHelpful' THEN 1 ELSE 0 END) AS not_helpful, "
                "sum(CASE WHEN coalesce(f.status, 'pending') = 'pending' "
                "THEN 1 ELSE 0 END) AS pending, "
                "sum(CASE WHEN f.review_action = 'approved' THEN 1 ELSE 0 END) AS approved, "
                "sum(CASE WHEN f.review_action = 'rejected' THEN 1 ELSE 0 END) AS dismissed"
            ).single()
            archived = session.run(
                "MATCH ()-[r]->() WHERE coalesce(r.archived, false) = true "
                "RETURN count(r) AS archived_triples"
            ).single()
        return {
            "total": totals["total"] or 0,
            "helpful": totals["helpful"] or 0,
            "not_helpful": totals["not_helpful"] or 0,
            "pending": totals["pending"] or 0,
            "approved": totals["approved"] or 0,
            "dismissed": totals["dismissed"] or 0,
            "archived_triples": archived["archived_triples"] or 0,
        }

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
    def _normalise_username(username: str) -> str:
        normalised = username.strip().lower()
        if (
            len(normalised) < 3
            or len(normalised) > 30
            or not normalised[0].isascii()
            or not normalised[0].isalnum()
            or any(
                not character.isascii()
                or not (character.isalnum() or character in "_.-")
                for character in normalised
            )
        ):
            raise ValueError(
                "Username must be 3-30 characters and use only letters, "
                "numbers, dots, underscores, or hyphens."
            )
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
