import asyncio
import math
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from adam.core.contracts import Contract, new_id
from adam.core.privacy import contains_secret
from adam.resilience.archive import scoped
from adam.resilience.contracts import BackupError
from adam.security.request import check_authority


class OperationsError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Schedule(Contract):
    request_id: UUID
    text: str = Field(min_length=1, max_length=500)
    due_at: datetime
    every_seconds: int | None = Field(default=None, ge=60, le=31536000)
    priority: Literal["NORMAL", "HIGH"] = "NORMAL"
    route: Literal["DESKTOP", "ACTIVE"] = "DESKTOP"
    session_id: UUID | None = None

    @field_validator("due_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Use a timestamp with explicit timezone")
        return value

    @field_validator("text")
    @classmethod
    def safe(cls, value: str) -> str:
        value = value.strip()
        if not value or contains_secret(value) or any(ord(c) < 32 for c in value):
            raise ValueError("Unsafe reminder text")
        return value


class Preferences(Contract):
    enabled: bool = True
    proactive: bool = False
    triggers: list[Literal["unread_reminders"]] = Field(default_factory=list, max_length=1)
    quiet_start: int | None = Field(default=None, ge=0, le=1439)
    quiet_end: int | None = Field(default=None, ge=0, le=1439)
    utc_offset_minutes: int = Field(default=300, ge=-720, le=840)


class Identifier(Contract):
    identifier: UUID


class Operations:
    """Durable local reminders. No background model/tool calls or captured credentials."""

    def __init__(self, root: Path, clock: Callable[[], float] = time.time) -> None:
        try:
            self.path = scoped(root, "operations/jobs.sqlite3")
        except BackupError:
            raise OperationsError("OPERATIONS.PATH_DENIED") from None
        self.root = root
        self.clock = clock
        self.worker: asyncio.Task[None] | None = None
        self.error: str | None = None
        self.active: dict[str, tuple[str, float]] = {}
        with self.db() as db:
            db.executescript(
                "CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY, value TEXT);"
                "CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, request TEXT UNIQUE, "
                "digest TEXT, text TEXT, due REAL, interval INTEGER, priority TEXT, route TEXT, "
                "session TEXT, state TEXT);"
                "CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY, job TEXT, "
                "occurrence REAL, text TEXT, priority TEXT, route TEXT, session TEXT, "
                "created REAL, ack INTEGER DEFAULT 0, reason TEXT, UNIQUE(job,occurrence));"
                "CREATE TABLE IF NOT EXISTS triggers(name TEXT PRIMARY KEY,last REAL);"
            )
            db.execute(
                "INSERT OR IGNORE INTO settings VALUES(1,?)", (Preferences().model_dump_json(),)
            )

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        try:
            scoped(self.root, "operations/jobs.sqlite3")
        except BackupError:
            raise OperationsError("OPERATIONS.PATH_DENIED") from None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            with db:
                yield db
        finally:
            db.close()

    def preferences(self) -> Preferences:
        with self.db() as db:
            return Preferences.model_validate_json(
                db.execute("SELECT value FROM settings").fetchone()[0]
            )

    def configure(self, value: Preferences) -> dict[str, Any]:
        if (value.quiet_start is None) != (value.quiet_end is None):
            raise OperationsError("OPERATIONS.QUIET_HOURS_INVALID")
        check_authority()
        with self.db() as db:
            check_authority()
            db.execute("UPDATE settings SET value=?", (value.model_dump_json(),))
            if not value.proactive:
                db.execute("UPDATE notifications SET ack=1 WHERE job LIKE 'trigger:%'")
        return value.model_dump()

    def create(self, value: Schedule) -> dict[str, Any]:
        due, now = value.due_at.timestamp(), self.clock()
        digest = value.model_dump_json()
        check_authority()
        with self.db() as db:
            check_authority()
            old = db.execute(
                "SELECT * FROM jobs WHERE request=?", (str(value.request_id),)
            ).fetchone()
            if old:
                if old["digest"] != digest:
                    raise OperationsError("OPERATIONS.ID_CONFLICT")
                return dict(old)
            if not math.isfinite(due) or due > now + 315360000 or due < now - 60:
                raise OperationsError("OPERATIONS.TIME_INVALID")
            if db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= 500:
                raise OperationsError("OPERATIONS.CAPACITY")
            identifier = new_id()
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    str(value.request_id),
                    digest,
                    value.text,
                    due,
                    value.every_seconds,
                    value.priority,
                    value.route,
                    str(value.session_id) if value.session_id else None,
                    "SCHEDULED",
                ),
            )
            return dict(db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone())

    def cancel(self, identifier: str) -> None:
        check_authority()
        with self.db() as db:
            check_authority()
            if not db.execute("SELECT 1 FROM jobs WHERE id=?", (identifier,)).fetchone():
                raise OperationsError("OPERATIONS.NOT_FOUND")
            db.execute("UPDATE jobs SET state='CANCELLED' WHERE id=?", (identifier,))
            db.execute("UPDATE notifications SET ack=1 WHERE job=?", (identifier,))

    @staticmethod
    def quiet(preferences: Preferences, now: float) -> bool:
        if preferences.quiet_start is None or preferences.quiet_end is None:
            return False
        minute = int((now / 60 + preferences.utc_offset_minutes) % 1440)
        start, end = preferences.quiet_start, preferences.quiet_end
        return start == end or (
            start <= minute < end if start < end else minute >= start or minute < end
        )

    def tick(self) -> None:
        now = self.clock()
        # Background permission is this narrow persisted enablement, not a login/elevation token.
        with self.db() as db:
            preferences = Preferences.model_validate_json(
                db.execute("SELECT value FROM settings").fetchone()[0]
            )
            if not preferences.enabled:
                return
            for job in db.execute(
                "SELECT * FROM jobs WHERE state='SCHEDULED' AND due<=? ORDER BY due LIMIT 50",
                (now,),
            ).fetchall():
                if (
                    db.execute("SELECT count(*) FROM notifications WHERE ack=0").fetchone()[0]
                    >= 1000
                ):
                    break  # Backpressure preserves the pending job; never silently drops it.
                db.execute(
                    "INSERT OR IGNORE INTO "
                    "notifications(id,job,occurrence,text,priority,route,session,created,reason) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        new_id(),
                        job["id"],
                        job["due"],
                        job["text"],
                        job["priority"],
                        job["route"],
                        job["session"],
                        now,
                        "Reminder explicitly scheduled by the desktop owner; due "
                        + datetime.fromtimestamp(job["due"]).astimezone().isoformat(),
                    ),
                )
                interval = job["interval"]
                if interval:
                    next_due = (
                        job["due"] + (math.floor((now - job["due"]) / interval) + 1) * interval
                    )
                    db.execute("UPDATE jobs SET due=? WHERE id=?", (next_due, job["id"]))
                else:
                    db.execute("UPDATE jobs SET state='COMPLETED' WHERE id=?", (job["id"],))
            if (
                preferences.proactive
                and "unread_reminders" in preferences.triggers
                and not self.quiet(preferences, now)
            ):
                old = db.execute(
                    "SELECT last FROM triggers WHERE name='unread_reminders'"
                ).fetchone()
                unread = db.execute(
                    "SELECT count(*) FROM notifications WHERE ack=0 AND created<=? "
                    "AND job NOT LIKE 'trigger:%'",
                    (now - 86400,),
                ).fetchone()[0]
                capacity = db.execute("SELECT count(*) FROM notifications WHERE ack=0").fetchone()[
                    0
                ]
                if unread and capacity < 1000 and (not old or now - old[0] >= 86400):
                    db.execute(
                        "INSERT INTO "
                        "notifications(id,job,occurrence,text,priority,route,created,reason) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (
                            new_id(),
                            "trigger:unread_reminders",
                            now,
                            "Review your unread reminders.",
                            "NORMAL",
                            "DESKTOP",
                            now,
                            "Opted-in unread_reminders trigger: at least one reminder has "
                            "been unread for 24 hours. Limited to once per 24 hours.",
                        ),
                    )
                    db.execute(
                        "INSERT OR REPLACE INTO triggers VALUES('unread_reminders',?)", (now,)
                    )
            db.execute("DELETE FROM notifications WHERE ack=1 AND created<?", (now - 30 * 86400,))
            db.execute(
                "DELETE FROM jobs WHERE state!='SCHEDULED' AND id NOT IN (SELECT "
                "job FROM notifications) AND due<?",
                (now - 30 * 86400,),
            )

    def seen(self, session: str, device: str) -> None:
        # Only the already authenticated session-primary device can register presence.
        self.active[session] = (device, self.clock())
        if len(self.active) > 1024:
            self.active = {k: v for k, v in self.active.items() if self.clock() - v[1] < 30}

    def inbox(
        self, device: str = "desktop", primary: Callable[[str], str] | None = None
    ) -> list[dict[str, Any]]:
        now = self.clock()
        preferences = self.preferences()
        if not preferences.enabled or self.quiet(preferences, now):
            return []
        with self.db() as db:
            result = []
            for row in db.execute(
                "SELECT * FROM notifications WHERE ack=0 "
                "ORDER BY (priority='HIGH') DESC,created LIMIT 1000"
            ):
                target = "desktop"
                if row["route"] == "ACTIVE" and row["session"] and primary:
                    candidate = primary(row["session"])
                    presence = self.active.get(row["session"])
                    if (
                        candidate != "desktop"
                        and presence
                        and presence[0] == candidate
                        and 0 <= now - presence[1] < 30
                    ):
                        target = candidate
                if target != device:
                    continue
                item = dict(row)
                # Mobile/lock-screen channel never contains private reminder text or session IDs.
                if device != "desktop":
                    item = {
                        "id": row["id"],
                        "priority": row["priority"],
                        "text": "ADAM update available. Review on your PC.",
                        "reason": "Owner scheduled update routed to this active device.",
                    }
                result.append(item)
                if len(result) >= 100:
                    break
            return result

    def acknowledge(self, identifier: str) -> None:
        check_authority()
        with self.db() as db:
            check_authority()
            db.execute("UPDATE notifications SET ack=1 WHERE id=?", (identifier,))

    def status(self) -> dict[str, Any]:
        with self.db() as db:
            jobs = [
                dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY due DESC LIMIT 500")
            ]
        return {
            "jobs": jobs,
            "preferences": self.preferences().model_dump(),
            "error": self.error,
            "triggers": {"unread_reminders": "Own reminder inbox only; 24-hour age and cooldown."},
            "execution": "REMINDERS_ONLY; task/tool execution requires fresh "
            "explicit approval on PC",
        }

    async def start(self) -> None:
        async def loop() -> None:
            while True:
                try:
                    await asyncio.to_thread(self.tick)
                    self.error = None
                except (sqlite3.Error, OSError, ValueError):
                    self.error = "OPERATIONS.STORE_UNAVAILABLE"
                await asyncio.sleep(1)

        self.worker = asyncio.create_task(loop())

    async def stop(self) -> None:
        if self.worker:
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker
            self.worker = None
