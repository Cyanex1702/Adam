import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from adam.core.contracts import Contract, SessionId, TraceId, new_id, utc_now
from adam.core.privacy import contains_secret
from adam.memory.service import Evidence, MemoryRecord, MemoryService, normalize
from adam.security.request import check_authority


class PersonalError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Link(Contract):
    id: str = Field(default_factory=new_id, pattern=r"^[a-f0-9-]{36}$")
    memory_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    subject: str = Field(min_length=1, max_length=120)
    relation: str = Field(min_length=1, max_length=80)
    object: str = Field(min_length=1, max_length=120)
    epistemic_status: Literal["REPORTED", "INFERRED"] = "REPORTED"


class Goal(Contract):
    id: str = Field(default_factory=new_id, pattern=r"^[a-f0-9-]{36}$")
    title: str = Field(min_length=1, max_length=300)
    project: str = Field(default="", max_length=120)
    status: Literal["ACTIVE", "PAUSED", "COMPLETED", "CANCELLED"] = "ACTIVE"
    progress: int = Field(default=0, ge=0, le=100)
    due: datetime | None = None
    revision: int = Field(default=0, ge=0)

    @field_validator("due")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Use a timestamp with timezone")
        return value.astimezone(UTC) if value else None


def clean(value: str) -> None:
    if contains_secret(value) or not normalize(value):
        raise PersonalError("PERSONAL.CONTENT_DENIED")


class Intelligence:
    def __init__(self, memories: MemoryService) -> None:
        self.memories = memories
        self.store = memories.store

    def evidence(self, memory_id: str, *, historical: bool = False) -> MemoryRecord:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT record FROM memories WHERE memory_id=?", (memory_id,)
            ).fetchone()
        if row:
            item = MemoryRecord.model_validate_json(row[0])
            if (
                self.memories.allowed(item)
                and not item.retracted
                and not item.generated_summary
                and (historical or item.status == "CURRENT")
            ):
                return item
        raise PersonalError("PERSONAL.EVIDENCE_UNAVAILABLE")

    def link(self, value: Link) -> dict[str, Any]:
        for label in [value.subject, value.relation, value.object]:
            clean(label)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            source = self.evidence(value.memory_id)
            words = normalize(source.key + " " + source.content)
            if any(normalize(label) not in words for label in [value.subject, value.object]):
                raise PersonalError("PERSONAL.UNSUPPORTED_ENTITIES")
            check_authority()
            db.execute(
                "INSERT INTO personal_links VALUES (?,?,?) ON CONFLICT(id) DO UPDATE "
                "SET memory_id=excluded.memory_id,record=excluded.record",
                (value.id, value.memory_id, value.model_dump_json()),
            )
        return self.explain(value)

    def explain(self, value: Link, *, historical: bool = False) -> dict[str, Any]:
        for label in [value.subject, value.relation, value.object]:
            clean(label)
        source = self.evidence(value.memory_id, historical=historical)
        return {
            **value.model_dump(mode="json"),
            "authority": "owner_annotation; source evidence takes precedence",
            "source_status": source.status,
            "source_epistemic_status": source.epistemic_status,
            "source": source.model_dump(mode="json"),
        }

    def graph(self, query: str = "", *, historical: bool = False) -> dict[str, Any]:
        terms = set(normalize(query).split())
        with self.store.connect() as db:
            rows = db.execute("SELECT record FROM personal_links ORDER BY id LIMIT 1001").fetchall()
        links = []
        for row in rows[:1000]:
            item = Link.model_validate_json(row[0])
            if terms and not terms.intersection(
                normalize(item.subject + " " + item.relation + " " + item.object).split()
            ):
                continue
            try:
                links.append(self.explain(item, historical=historical))
            except PersonalError:
                continue
        return {
            "links": links[:100],
            "truncated": len(links) > 100 or len(rows) > 1000,
            "note": "Explicit annotations, never independent proof or action permission.",
        }

    def delete(self, kind: Literal["link", "goal"], identifier: str) -> None:
        table = "personal_links" if kind == "link" else "personal_goals"
        with self.store.connect() as db:
            check_authority()
            db.execute(f"DELETE FROM {table} WHERE id=?", (identifier,))

    def timeline(
        self,
        query: str = "",
        start: datetime | None = None,
        end: datetime | None = None,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        for value in [start, end, as_of]:
            if value is not None and value.tzinfo is None:
                raise PersonalError("PERSONAL.TIMEZONE_REQUIRED")
        if start and end and start > end:
            raise PersonalError("PERSONAL.INVALID_RANGE")
        terms = set(normalize(query).split())
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT record FROM memories ORDER BY rowid DESC LIMIT 2001"
            ).fetchall()
        result = []
        for row in rows[:2000]:
            item = MemoryRecord.model_validate_json(row[0])
            if not self.memories.allowed(item) or item.retracted or item.generated_summary:
                continue
            if terms and not terms.intersection(normalize(item.key + " " + item.content).split()):
                continue
            if (start and item.valid_from < start) or (end and item.valid_from > end):
                continue
            if as_of and (
                item.valid_from > as_of
                or (item.valid_until and item.valid_until <= as_of)
                or item.status == "POSSIBLE"
            ):
                continue
            result.append(item.model_dump(mode="json"))
        result.sort(
            key=lambda item: (str(item["valid_from"]), str(item["memory_id"])), reverse=True
        )
        return {
            "events": result[:100],
            "truncated": len(result) > 100 or len(rows) > 2000,
            "as_of": as_of.isoformat() if as_of else None,
            "note": "Recorded owner claims, with valid-time history; not independently verified.",
        }

    def save_goal(self, value: Goal) -> dict[str, Any]:
        clean(value.title + " " + value.project)
        if (value.status == "COMPLETED") != (value.progress == 100):
            raise PersonalError("PERSONAL.COMPLETION_PROGRESS_MISMATCH")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT memory_id,record FROM personal_goals WHERE id=?", (value.id,)
            ).fetchone()
            expected = Goal.model_validate_json(old[1]).revision if old else 0
            if value.revision != expected:
                raise PersonalError("PERSONAL.STALE_REVISION")
            check_authority()
            sid = SessionId(new_id())
            now = utc_now()
            # Evidence uses a non-conversation explicit UI event, not a fabricated utterance.
            memory = self.memories.remember(
                db,
                key="goal " + value.id,
                content=value.title + (" [" + value.project + "]" if value.project else ""),
                kind="goal",
                evidence=Evidence(
                    source="explicit_goal_form",
                    session_id=sid,
                    trace_id=TraceId(new_id()),
                    timestamp=now,
                ),
            )
            updated = value.model_copy(update={"revision": expected + 1})
            db.execute(
                "INSERT INTO personal_goals VALUES (?,?,?) ON CONFLICT(id) DO UPDATE "
                "SET memory_id=excluded.memory_id,record=excluded.record",
                (value.id, memory.memory_id, updated.model_dump_json()),
            )
            db.execute(
                "INSERT INTO personal_goal_events(goal_id,occurred_at,status,progress) "
                "VALUES (?,?,?,?)",
                (value.id, now.isoformat(), value.status, value.progress),
            )
        return updated.model_dump(mode="json")

    def goals(self) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT memory_id,record FROM personal_goals ORDER BY id LIMIT 500"
            ).fetchall()
        values = []
        for row in rows:
            try:
                self.evidence(row[0])
            except PersonalError:
                continue
            value = Goal.model_validate_json(row[1]).model_dump(mode="json")
            if contains_secret(json.dumps(value)):
                continue
            with self.store.connect() as db:
                history = db.execute(
                    "SELECT occurred_at,status,progress FROM personal_goal_events "
                    "WHERE goal_id=? ORDER BY id DESC LIMIT 100",
                    (value["id"],),
                ).fetchall()
            value["memory_id"] = row[0]
            value["history"] = [dict(event) for event in history]
            values.append(value)
        return values

    def briefing(self) -> dict[str, Any]:
        goals = self.goals()
        now = utc_now()
        active = [item for item in goals if item["status"] == "ACTIVE"]
        return {
            "generated_at": now.isoformat(),
            "active_goals": active,
            "overdue_ids": [
                item["id"]
                for item in active
                if item["due"] and datetime.fromisoformat(item["due"]) < now
            ],
            "routine_candidates": self.routines(),
            "delivery": "manual_only; no reminders or external actions scheduled",
        }

    def routines(self) -> list[dict[str, Any]]:
        # Repeated explicit episodic records on distinct dates; suggestions are never promoted.
        events = self.timeline()["events"]
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in events:
            if item["type"] == "episodic" and item["epistemic_status"] == "REPORTED":
                groups.setdefault(normalize(item["content"]), []).append(item)
        result = []
        for events in groups.values():
            days = {
                datetime.fromisoformat(source["timestamp"]).date()
                for item in events
                for source in item["provenance"]
            }
            if len(days) < 3:
                continue
            result.append(
                {
                    "description": events[0]["content"],
                    "epistemic_status": "INFERRED",
                    "distinct_days": len(days),
                    "evidence_ids": [item["memory_id"] for item in events],
                    "why": "Same explicit episodic statement recorded on at least three dates.",
                    "correction": "Correct, retract or forget the supporting memory records.",
                    "authority": "suggestion_only",
                }
            )
        return result[:20]
