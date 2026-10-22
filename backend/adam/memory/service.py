from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from adam.core.contracts import Contract, SessionId, TraceId, new_id, utc_now
from adam.core.privacy import contains_secret
from adam.core.storage import ConversationStore
from adam.security.policy import Mode, Principal, ResourcePolicy, decide

MemoryType = Literal["semantic", "episodic", "preference", "project", "goal"]
Privacy = Literal["PUBLIC", "PERSONAL", "PRIVATE", "CONFIDENTIAL"]


class MemoryCommandError(ValueError):
    """Fixed, safe command guidance; never contains user input or backend diagnostics."""


class Evidence(Contract):
    source: str = "explicit_owner_statement"
    source_actor: str = "local_user"
    device_id: str = "local_desktop"
    session_id: SessionId
    trace_id: TraceId
    timestamp: datetime


class MemoryRecord(Contract):
    memory_id: str
    profile: Mode = "owner"
    key: str
    content: str = Field(min_length=1, max_length=2000)
    type: MemoryType
    classification: Literal["FACT", "PREFERENCE", "POSSIBILITY", "INTENTION"] = "FACT"
    subjects: list[str] = Field(default_factory=lambda: ["owner"])
    allowed_audiences: list[str] = Field(default_factory=lambda: ["owner"])
    disclosure_owner: str = "owner"
    replication_policy: str = "local_only"
    epistemic_status: Literal["REPORTED", "UNCERTAIN"] = "REPORTED"
    confidence: float = Field(default=0.9, ge=0, le=1)
    importance: float = Field(default=0.7, ge=0, le=1)
    privacy: Privacy = "PERSONAL"
    created_at: datetime
    valid_from: datetime
    valid_until: datetime | None = None
    status: Literal["CURRENT", "HISTORICAL", "POSSIBLE"] = "CURRENT"
    pinned: bool = False
    retention: Literal["PINNED", "LONG_TERM", "TEMPORARY", "ARCHIVAL"] = "LONG_TERM"
    tier: Literal["HOT", "WARM", "COLD"] = "HOT"
    last_accessed: datetime | None = None
    access_count: int = 0
    provenance: list[Evidence]
    supersedes: str | None = None
    retrieval_priority: float = Field(default=0.7, ge=0, le=1)
    decay_as_of: str | None = None
    archive_reason: Literal["owner", "low_importance"] | None = None
    generated_summary: bool = False
    summary_of: list[str] = Field(default_factory=list)
    retracted: bool = False


@dataclass
class MemoryCommand:
    action: str
    argument: str


def normalize(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"\bvs\s*code\b", "vscode", value)
    return re.sub(r"[^\w]+", " ", value).strip()


def parse_command(text: str) -> MemoryCommand | None:
    patterns = [
        ("candidates", r"^/candidates\s*(.*)$"),
        ("accept_candidate", r"^/accept\s+(.+)$"),
        ("reject_candidate", r"^/reject\s+(.+)$"),
        ("consolidate", r"^/consolidate\s*(.*)$"),
        ("archive", r"^/archive\s+(.+)$"),
        ("pin", r"^/pin\s+(.+)$"),
        ("unpin", r"^/unpin\s+(.+)$"),
        ("remember", r"^/?remember(?: this)?(?: permanently)?\s*:?\s*(.*)$"),
        ("correct", r"^/?correct\s+(.*)$"),
        ("forget", r"^/?forget(?: that)?\s*:?\s*(.*)$"),
        ("show", r"^/?show memory\s*:?\s*(.*)$"),
        ("show", r"^show what you remember(?: about)?\s*(.*)$"),
        ("why", r"^/?why (?:know|do you know that\??)\s*(.*)$"),
        ("reject", r"^that is wrong[.!]?$"),
    ]
    for action, pattern in patterns:
        match = re.match(pattern, text.strip(), re.IGNORECASE)
        if match:
            argument = match.group(1).strip() if match.lastindex else ""
            if action == "forget" and argument in {".", "!", "?"}:
                argument = ""
            if action == "remember" and "permanently" in text[:35].casefold():
                argument = "--pin " + argument
            return MemoryCommand(action, argument)
    return None


class MemoryService:
    def __init__(self, store: ConversationStore, principal: Principal | None = None) -> None:
        self.store = store
        self.principal = principal or Principal()

    def allowed(self, item: MemoryRecord) -> bool:
        if contains_secret(item.key + " " + item.content):
            return False
        return decide(
            self.principal,
            ResourcePolicy(
                replication_policy=item.replication_policy,
                sensitivity=item.privacy,
                allowed_audiences=item.allowed_audiences,
                subjects=item.subjects,
                disclosure_owner=item.disclosure_owner,
                source_actor=item.provenance[0].source_actor if item.provenance else "unknown",
                profile=item.profile,
            ),
        ).allowed

    @staticmethod
    def save(db: sqlite3.Connection, memory: MemoryRecord) -> None:
        previous_row = db.execute(
            "SELECT record FROM memories WHERE memory_id=?", (memory.memory_id,)
        ).fetchone()
        if previous_row and not memory.generated_summary:
            previous = MemoryRecord.model_validate_json(previous_row[0])
            if any(
                getattr(previous, field) != getattr(memory, field)
                for field in ["content", "status", "tier", "privacy"]
            ):
                for row in db.execute("SELECT record FROM memories").fetchall():
                    derived = MemoryRecord.model_validate_json(row[0])
                    if memory.memory_id in derived.summary_of:
                        db.execute("DELETE FROM memories WHERE memory_id=?", (derived.memory_id,))
        db.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?) ON CONFLICT(memory_id) DO UPDATE "
            "SET memory_key=excluded.memory_key,status=excluded.status,tier=excluded.tier,"
            "privacy=excluded.privacy,record=excluded.record",
            (
                memory.memory_id,
                normalize(memory.key),
                memory.status,
                memory.tier,
                memory.privacy,
                memory.model_dump_json(),
            ),
        )

    def search(
        self,
        query: str = "",
        *,
        historical: bool = False,
        archived: bool = False,
        limit: int = 20,
        db: sqlite3.Connection | None = None,
    ) -> list[MemoryRecord]:
        if db is None:
            with self.store.connect() as connection:
                return self.search(
                    query, historical=historical, archived=archived, limit=limit, db=connection
                )
        # Policy and secret filtering precede matching and model context.
        rows = db.execute(
            "SELECT record FROM memories WHERE privacy IN "
            "('PUBLIC','PERSONAL','PRIVATE','CONFIDENTIAL') "
            "AND (? OR status='CURRENT') AND (? OR tier<>'COLD')",
            (historical, archived),
        ).fetchall()
        terms = set(normalize(query).split())
        ranked = []
        for row in rows:
            item = MemoryRecord.model_validate_json(row[0])
            if not self.allowed(item):
                continue
            words = set(normalize(item.key + " " + item.content).split())
            score = len(terms & words)
            if terms and not score and query != item.memory_id:
                continue
            ranked.append((score, item.pinned, item.retrieval_priority, item.created_at, item))
        ranked.sort(key=lambda row: row[:4], reverse=True)
        return [row[-1] for row in ranked[: max(1, min(limit, 100))]]

    def _select(self, db: sqlite3.Connection, target: str, session_id: SessionId) -> MemoryRecord:
        if not target:
            row = db.execute(
                "SELECT memory_focus FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            target = row[0] if row and row[0] else ""
        found = (
            [
                MemoryRecord.model_validate_json(row[0])
                for row in db.execute(
                    "SELECT record FROM memories WHERE memory_id=? OR memory_key=?",
                    (target, normalize(target)),
                ).fetchall()
            ]
            if target
            else []
        )
        exact = [item for item in found if item.memory_id == target]
        found = [item for item in found if self.allowed(item)]
        exact = [item for item in exact if self.allowed(item)]
        if not exact:
            exact = [
                item
                for item in found
                if normalize(item.key) == normalize(target) and item.status == "CURRENT"
            ]
        if not exact:
            family = [item for item in found if normalize(item.key) == normalize(target)]
            exact = sorted(family, key=lambda item: item.created_at, reverse=True)[:1]
        if len(exact) != 1:
            raise MemoryCommandError(
                "Specify one exact memory ID or current key; no memory was changed."
            )
        return exact[0]

    def remember(
        self,
        db: sqlite3.Connection,
        *,
        key: str,
        content: str,
        kind: MemoryType,
        evidence: Evidence,
        pinned: bool = False,
        privacy: Privacy = "PERSONAL",
        importance: float = 0.7,
        replace: MemoryRecord | None = None,
    ) -> MemoryRecord:
        if contains_secret(key + " " + content) or not normalize(content) or len(content) > 2000:
            raise MemoryCommandError("Memory content is empty, too long, or credential-bearing.")
        if not normalize(key) or len(key) > 100:
            raise MemoryCommandError("Memory key must be 1 to 100 characters.")
        uncertain = bool(
            re.search(
                r"\b(might|may|maybe|perhaps|possibly|considering|shayad|unsure)\b|"
                r"not sure|I (?:think|guess|believe)",
                content,
                re.IGNORECASE,
            )
        )
        current = [
            MemoryRecord.model_validate_json(row[0])
            for row in db.execute(
                "SELECT record FROM memories WHERE memory_key=?", (normalize(key),)
            ).fetchall()
        ]
        for item in current:
            if (
                normalize(item.key) == normalize(key)
                and normalize(item.content) == normalize(content)
                and item.status != "HISTORICAL"
            ):
                if evidence not in item.provenance:
                    item.provenance.append(evidence)
                item.pinned = item.pinned or pinned
                item.retention = "PINNED" if item.pinned else item.retention
                self.save(db, item)
                return item
        previous = replace or next(
            (
                item
                for item in current
                if normalize(item.key) == normalize(key) and item.status == "CURRENT"
            ),
            None,
        )
        now = evidence.timestamp
        if previous and not uncertain:
            previous.status = "HISTORICAL"
            previous.valid_until = now
            self.save(db, previous)
        memory = MemoryRecord(
            memory_id=new_id(),
            profile=self.principal.mode,
            subjects=[self.principal.person_id],
            allowed_audiences=[self.principal.person_id],
            disclosure_owner=self.principal.person_id,
            key=key.strip(),
            content=content.strip(),
            type=kind,
            classification="POSSIBILITY"
            if uncertain
            else (
                "PREFERENCE"
                if kind == "preference"
                else ("INTENTION" if kind == "goal" else "FACT")
            ),
            epistemic_status="UNCERTAIN" if uncertain else "REPORTED",
            confidence=0.4 if uncertain else 0.9,
            importance=importance,
            retrieval_priority=importance,
            privacy=privacy,
            created_at=now,
            valid_from=now,
            status="POSSIBLE" if uncertain else "CURRENT",
            pinned=pinned,
            retention="PINNED" if pinned else "LONG_TERM",
            provenance=[evidence],
            supersedes=previous.memory_id if previous and not uncertain else None,
        )
        self.save(db, memory)
        return memory

    def execute(
        self,
        db: sqlite3.Connection,
        command: MemoryCommand,
        session_id: SessionId,
        trace_id: TraceId,
    ) -> tuple[str, dict[str, Any]]:
        action, argument = command.action, command.argument
        if action == "remember":
            pinned = "--pin" in argument
            argument = argument.replace("--pin", "").strip()
            privacy: Privacy = "PRIVATE" if argument.startswith("--private ") else "PERSONAL"
            argument = argument.removeprefix("--private ").strip()
            kind: MemoryType = "semantic"
            for name in ["semantic", "episodic", "preference", "project", "goal"]:
                if argument.startswith(name + " "):
                    kind = name  # type: ignore[assignment]
                    argument = argument[len(name) + 1 :]
                    break
            if "=" in argument:
                key, content = map(str.strip, argument.split("=", 1))
            else:
                content = argument
                match = re.match(r"my (.{1,60}?) (?:is|are) (.+)", content, re.IGNORECASE)
                key = (
                    match.group(1)
                    if match
                    else "statement " + hashlib.sha256(normalize(content).encode()).hexdigest()[:12]
                )
                if re.match(r"I prefer\b", content, re.IGNORECASE):
                    kind = "preference"
            memory = self.remember(
                db,
                key=key,
                content=content,
                kind=kind,
                pinned=pinned,
                privacy=privacy,
                evidence=Evidence(session_id=session_id, trace_id=trace_id, timestamp=utc_now()),
            )
            db.execute(
                "UPDATE sessions SET memory_focus=? WHERE session_id=?",
                (memory.memory_id, session_id),
            )
            return (
                f"Remembered {memory.memory_id}: {memory.content} "
                f"({memory.status}, {memory.epistemic_status}).",
                {"memory": memory.model_dump(mode="json")},
            )
        if action == "correct":
            if "=" not in argument:
                raise MemoryCommandError("Use /correct KEY_OR_ID = replacement statement.")
            target, content = map(str.strip, argument.split("=", 1))
            previous = self._select(db, target, session_id)
            memory = self.remember(
                db,
                key=previous.key,
                content=content,
                kind=previous.type,
                pinned=previous.pinned,
                privacy=previous.privacy,
                importance=previous.importance,
                evidence=Evidence(session_id=session_id, trace_id=trace_id, timestamp=utc_now()),
                replace=previous,
            )
            db.execute(
                "UPDATE sessions SET memory_focus=? WHERE session_id=?",
                (memory.memory_id, session_id),
            )
            return (
                f"Correction saved: {memory.memory_id}: {memory.content} ({memory.status}). "
                "Prior confirmed values are historical; possibilities do not replace facts.",
                {"memory": memory.model_dump(mode="json")},
            )
        if action == "reject":
            memory = self._select(db, "", session_id)
            memory.status = "HISTORICAL"
            memory.valid_until = utc_now()
            memory.retracted = True
            memory.confidence = 0
            memory.epistemic_status = "UNCERTAIN"
            memory.provenance.append(
                Evidence(
                    source="owner_retracted_statement",
                    session_id=session_id,
                    trace_id=trace_id,
                    timestamp=utc_now(),
                )
            )
            self.save(db, memory)
            return (
                "Marked the focused memory as historical. "
                "Use /correct KEY = replacement to provide the right value.",
                {"memory": memory.model_dump(mode="json")},
            )
        if action == "forget":
            memory = self._select(db, argument, session_id)
            family = [
                MemoryRecord.model_validate_json(row[0])
                for row in db.execute(
                    "SELECT record FROM memories WHERE memory_key=?", (normalize(memory.key),)
                )
            ]
            ids = [item.memory_id for item in family]
            traces = {str(e.trace_id) for item in family for e in item.provenance}
            phrases = {item.content.casefold() for item in family}
            # Remove supporting/echoed turns too, so forgotten material is not supplied through
            # recent history or a summary. SQLite secure_delete scrubs removed record payloads.
            db.execute("PRAGMA secure_delete=ON")
            for item in family:
                db.execute("DELETE FROM memories WHERE memory_id=?", (item.memory_id,))
            # Derived summaries cannot retain a deleted source.
            for row in db.execute("SELECT record FROM memories").fetchall():
                derived = MemoryRecord.model_validate_json(row[0])
                if set(derived.summary_of) & set(ids):
                    db.execute("DELETE FROM memories WHERE memory_id=?", (derived.memory_id,))
            for row in db.execute("SELECT candidate_id,record FROM memory_candidates").fetchall():
                candidate_text = row["record"].casefold()
                if any(phrase in candidate_text for phrase in phrases) or any(
                    trace in candidate_text for trace in traces
                ):
                    db.execute(
                        "DELETE FROM memory_candidates WHERE candidate_id=?", (row["candidate_id"],)
                    )
            for row in db.execute(
                "SELECT turn_id,user_text,assistant_text,trace_id FROM turns"
            ).fetchall():
                text = (row["user_text"] + " " + row["assistant_text"]).casefold()
                if (
                    row["trace_id"] in traces
                    or any(phrase in text for phrase in phrases)
                    or any(mid in text for mid in ids)
                ):
                    db.execute("DELETE FROM turns WHERE turn_id=?", (row["turn_id"],))
            db.execute("UPDATE sessions SET summary='',summary_through=0,memory_focus=NULL")
            for row in db.execute("SELECT session_id,working_state FROM sessions").fetchall():
                state = json.loads(row["working_state"])

                def related(value: str) -> bool:
                    return any(phrase in value.casefold() for phrase in phrases)

                for field in ["objective", "task_state"]:
                    if related(state.get(field, "")):
                        state[field] = ""
                for field in ["instructions", "active_entities"]:
                    state[field] = [value for value in state.get(field, []) if not related(value)]
                db.execute(
                    "UPDATE sessions SET working_state=? WHERE session_id=?",
                    (json.dumps(state), row["session_id"]),
                )
            return (
                "Forgot the memory key, its historical versions, "
                "and identifiable supporting/echoed conversation turns.",
                {"forgotten_ids": ids},
            )
        if action == "why":
            memory = self._select(db, argument, session_id)
            return "Owner statement provenance: " + json.dumps(
                memory.model_dump(mode="json"), ensure_ascii=False
            ), {"memory": memory.model_dump(mode="json")}
        if action == "show":
            historical = "--history" in argument
            archived = "--archive" in argument
            query = argument.replace("--history", "").replace("--archive", "").strip()
            found = self.search(query, historical=historical, archived=archived, db=db)
            if len(found) == 1:
                db.execute(
                    "UPDATE sessions SET memory_focus=? WHERE session_id=?",
                    (found[0].memory_id, session_id),
                )
            else:
                db.execute(
                    "UPDATE sessions SET memory_focus=NULL WHERE session_id=?", (session_id,)
                )
            records = [item.model_dump(mode="json") for item in found]
            return (
                json.dumps(records, ensure_ascii=False, indent=2)
                if found
                else "I have no matching confirmed memory. I do not know."
            ), {"memories": records}
        raise MemoryCommandError("Unsupported memory command.")

    def context(self, query: str, session_id: SessionId | None = None) -> str:
        found = self.search(query, limit=6)
        with self.store.connect() as db:
            if session_id:
                db.execute(
                    "UPDATE sessions SET memory_focus=? WHERE session_id=?",
                    (found[0].memory_id if len(found) == 1 else None, session_id),
                )
            for item in found:
                item.last_accessed = utc_now()
                item.access_count += 1
                self.save(db, item)
        # Bounded record extracts; references remain inspectable through /why and API.
        return (
            json.dumps(
                [
                    {
                        "id": item.memory_id,
                        "key": item.key,
                        "content": item.content,
                        "status": item.status,
                        "epistemic_status": item.epistemic_status,
                        "source": [e.model_dump(mode="json") for e in item.provenance[-2:]],
                    }
                    for item in found
                ],
                ensure_ascii=False,
            )
            if found
            else ""
        )
