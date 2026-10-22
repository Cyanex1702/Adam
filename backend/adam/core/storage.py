import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import time
from typing import Any

from adam.core.contracts import AdamError, ErrorEnvelope, SessionId, TraceId, utc_now
from adam.core.migrations import migrate
from adam.core.privacy import contains_secret, safe_transcript
from adam.core.working import ContextBudget, WorkingState
from adam.models.base import Message


class ConversationStore:
    def __init__(self, path: Path, recent_turns: int = 8) -> None:
        self.path = path
        self.recent_turns = recent_turns
        migrate(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, session_id: SessionId) -> None:
        now = utc_now().isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO sessions(session_id,created_at,updated_at) VALUES (?,?,?)",
                (session_id, now, now),
            )

    def get(self, session_id: SessionId) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            return dict(row) if row else None

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
                )
            ]

    def history(
        self, session_id: SessionId, limit: int = 100, before: int | None = None
    ) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM turns WHERE session_id=? AND (? IS NULL OR turn_id<?) "
                "ORDER BY turn_id DESC LIMIT ?",
                (session_id, before, before, limit),
            ).fetchall()
            return [
                {
                    **dict(row),
                    "user_text": safe_transcript(row["user_text"]),
                    "assistant_text": safe_transcript(row["assistant_text"]),
                }
                for row in reversed(rows)
            ]

    def recent(self, session_id: SessionId, limit: int) -> list[Message]:
        return [
            message
            for row in self.history(session_id, limit)
            if row["model_id"] != "grounded_source_service"
            for message in [
                Message(role="user", content=row["user_text"]),
                Message(role="assistant", content=row["assistant_text"]),
            ]
        ]

    def append(
        self,
        session_id: SessionId,
        user: str,
        assistant: str,
        trace_id: TraceId,
        model_id: str,
        expected_memory_revision: int | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if expected_memory_revision is not None:
                row = db.execute(
                    "SELECT value FROM runtime_metadata WHERE key='memory_revision'"
                ).fetchone()
                if (int(row[0]) if row else 0) != expected_memory_revision:
                    raise AdamError(
                        ErrorEnvelope(
                            code="MEMORY.CONTEXT_CHANGED",
                            trace_id=trace_id,
                            message="Memory changed during generation. Retry with updated context.",
                            retryable=True,
                        )
                    )
            self.append_in(db, session_id, user, assistant, trace_id, model_id)

    def append_in(
        self,
        db: sqlite3.Connection,
        session_id: SessionId,
        user: str,
        assistant: str,
        trace_id: TraceId,
        model_id: str,
    ) -> None:
        now = utc_now().isoformat()
        db.execute(
            "INSERT INTO turns(session_id,user_text,assistant_text,created_at,"
            "trace_id,model_id) VALUES (?,?,?,?,?,?)",
            (
                session_id,
                safe_transcript(user),
                safe_transcript(assistant),
                now,
                trace_id,
                model_id,
            ),
        )
        db.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (now, session_id))
        self._roll_summary(db, session_id)

    def _roll_summary(self, db: sqlite3.Connection, session_id: SessionId) -> None:
        row = db.execute(
            "SELECT summary,summary_through FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        boundary = db.execute(
            "SELECT turn_id FROM turns WHERE session_id=? ORDER BY turn_id DESC LIMIT 1 OFFSET ?",
            (session_id, self.recent_turns),
        ).fetchone()
        if not boundary:
            return
        older = db.execute(
            "SELECT turn_id,user_text,assistant_text,model_id FROM turns "
            "WHERE session_id=? AND turn_id>? AND turn_id<=? "
            "ORDER BY turn_id LIMIT 64",
            (session_id, row["summary_through"], boundary[0]),
        ).fetchall()
        if not older:
            return
        lines = row["summary"].splitlines()
        for turn in older:
            if turn["model_id"] == "grounded_source_service":
                continue
            lines.append(
                f"turn:{turn['turn_id']} owner excerpt (incomplete): {turn['user_text'][:180]} | "
                f"assistant (unverified): {turn['assistant_text'][:100]}"
            )
        # Keep whole records, never convert a possibility into an assertion.
        while sum(len(line) + 1 for line in lines) > 2048:
            lines.pop(0)
        db.execute(
            "UPDATE sessions SET summary=?,summary_through=? WHERE session_id=?",
            ("\n".join(lines), older[-1]["turn_id"], session_id),
        )

    def working(self, session_id: SessionId) -> WorkingState:
        row = self.get(session_id)
        if not row:
            raise ValueError("Session not found")
        return WorkingState.model_validate_json(row["working_state"])

    def set_working(self, session_id: SessionId, state: WorkingState) -> None:
        state = WorkingState.model_validate(state.model_dump())
        data = state.model_dump_json()
        if len(data) > 12000 or contains_secret(data):
            raise ValueError("Working state is too large or contains credentials")
        with self.connect() as db:
            if not db.execute(
                "UPDATE sessions SET working_state=? WHERE session_id=?", (data, session_id)
            ).rowcount:
                raise ValueError("Session not found")

    def set_budget(self, session_id: SessionId, budget: ContextBudget) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE sessions SET context_budget=? WHERE session_id=?",
                (json.dumps(budget.model_dump()), session_id),
            )

    def close(self, session_id: SessionId) -> bool:
        with self.connect() as db:
            return bool(
                db.execute(
                    "UPDATE sessions SET closed=1 WHERE session_id=? AND closed=0 "
                    "AND lease_until<?",
                    (session_id, time()),
                ).rowcount
            )

    def reopen(self, session_id: SessionId) -> bool:
        with self.connect() as db:
            return bool(
                db.execute(
                    "UPDATE sessions SET closed=0 WHERE session_id=? AND lease_until<?",
                    (session_id, time()),
                ).rowcount
            )

    def memory_revision(self) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT value FROM runtime_metadata WHERE key='memory_revision'"
            ).fetchone()
            return int(row[0]) if row else 0

    @staticmethod
    def bump_memory_revision(db: sqlite3.Connection) -> None:
        db.execute(
            "INSERT INTO runtime_metadata VALUES ('memory_revision','1') "
            "ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1"
        )

    def acquire(self, session_id: SessionId, trace_id: TraceId) -> bool:
        with self.connect() as db:
            return bool(
                db.execute(
                    "UPDATE sessions SET lease_owner=?,lease_until=? "
                    "WHERE session_id=? AND closed=0 AND lease_until<?",
                    (trace_id, time() + 60, session_id, time()),
                ).rowcount
            )

    def renew(self, session_id: SessionId, trace_id: TraceId) -> bool:
        with self.connect() as db:
            return bool(
                db.execute(
                    "UPDATE sessions SET lease_until=? "
                    "WHERE session_id=? AND lease_owner=? AND lease_until>=?",
                    (time() + 60, session_id, trace_id, time()),
                ).rowcount
            )

    def release(self, session_id: SessionId, trace_id: TraceId) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE sessions SET lease_owner=NULL,lease_until=0 "
                "WHERE session_id=? AND lease_owner=?",
                (session_id, trace_id),
            )
