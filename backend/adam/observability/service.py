import os
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from pydantic import Field

from adam.core.contracts import Contract, EventEnvelope, new_id
from adam.core.privacy import contains_secret


class TraceConfig(Contract):
    level: Literal["OFF", "ERROR", "NORMAL", "DEBUG", "TRACE"] = "NORMAL"
    retention_days: int = Field(default=7, ge=1, le=90)
    max_events: int = Field(default=10000, ge=100, le=100000)


class Point(Contract):
    event_id: str
    trace_id: str
    timestamp: float
    subsystem: str
    event: str
    status: str
    duration_ms: float | None = None
    error_code: str | None = None
    references: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float | bool] = Field(default_factory=dict)


class TraceService:
    def __init__(self, data_dir: Path, config: TraceConfig | None = None) -> None:
        self.config = config or TraceConfig()
        self.path = data_dir / "audit" / "turns.jsonl"
        self.database = data_dir / "audit" / "traces.sqlite3"

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database, timeout=3)) as db, db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise ValueError("TRACE.UNSUPPORTED_SCHEMA")
            db.execute(
                "CREATE TABLE IF NOT EXISTS events("
                "id TEXT PRIMARY KEY, trace TEXT, timestamp REAL, record TEXT)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS events_trace ON events(trace,timestamp)")
            db.execute("PRAGMA user_version=1")
            yield db

    def emit(
        self,
        trace_id: str,
        subsystem: str,
        event: str,
        status: str,
        *,
        duration_ms: float | None = None,
        error_code: str | None = None,
        references: list[str] | None = None,
        metrics: dict[str, int | float | bool] | None = None,
    ) -> None:
        if self.config.level == "OFF" or (
            self.config.level == "ERROR"
            and not error_code
            and status not in {"FAILED", "UNCERTAIN"}
        ):
            return
        # Reject free-form labels and references. Text/file bodies are never accepted.
        labels = [subsystem, event, status, *(metrics or {}).keys()]
        if not re.fullmatch(r"[a-fA-F0-9-]{36}", trace_id):
            return
        if error_code:
            labels.append(error_code)
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", label) for label in labels):
            return
        refs = [ref for ref in references or [] if re.fullmatch(r"[a-fA-F0-9-]{16,64}", ref)]
        point = Point(
            event_id=new_id(),
            trace_id=trace_id,
            timestamp=time.time(),
            subsystem=subsystem,
            event=event,
            status=status,
            duration_ms=duration_ms,
            error_code=error_code,
            references=refs,
            metrics=metrics or {},
        )
        encoded = point.model_dump_json()
        if contains_secret(encoded):
            return
        with self.connect() as db:
            db.execute(
                "INSERT INTO events VALUES(?,?,?,?)",
                (point.event_id, trace_id, point.timestamp, encoded),
            )
            self.prune(db)

    def prune(self, db: sqlite3.Connection) -> None:
        db.execute(
            "DELETE FROM events WHERE timestamp < ?",
            (time.time() - self.config.retention_days * 86400,),
        )
        db.execute(
            "DELETE FROM events WHERE rowid NOT IN "
            "(SELECT rowid FROM events ORDER BY rowid DESC LIMIT ?)",
            (self.config.max_events,),
        )

    def list(self, trace_id: str | None = None, limit: int = 200) -> list[Point]:
        if not self.database.exists():
            return []
        with self.connect() as db:
            self.prune(db)
            rows = db.execute(
                "SELECT record FROM events WHERE (? IS NULL OR trace=?) "
                "ORDER BY rowid DESC LIMIT ?",
                (trace_id, trace_id, max(1, min(limit, 1000))),
            ).fetchall()
        result = []
        for row in reversed(rows):
            if contains_secret(row[0]):
                continue
            try:
                result.append(Point.model_validate_json(row[0]))
            except ValueError:
                continue
        return result

    def record(self, event: EventEnvelope) -> None:
        """Compatibility turn receipt. Only fixed metadata keys survive serialization."""
        if (
            event.sensitivity in {"NEVER_LOG", "SECRET", "SYSTEM_SECRET", "NEVER_LLM"}
            or event.event_type != "agent.turn_trace"
            or contains_secret(event.model_dump_json())
        ):
            return
        safe = event.model_copy(
            update={
                "payload": {
                    key: value
                    for key, value in event.payload.items()
                    if key in {"status", "error_code", "model", "answer_provider", "elapsed_ms"}
                }
            }
        )
        encoded = safe.model_dump_json()
        if contains_secret(encoded) or self.config.level == "OFF":
            return
        status = str(safe.payload.get("status", "UNKNOWN"))
        code = safe.payload.get("error_code")
        if self.config.level == "ERROR" and not code and status != "FAILED":
            return
        self.emit(
            str(event.trace_id),
            "runtime",
            "turn",
            status,
            duration_ms=float(str(safe.payload.get("elapsed_ms", 0))),
            error_code=str(code) if code else None,
        )
        # Keep the legacy file bounded, serialized across processes by the trace DB.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text("\n".join([*lines[-999:], encoded]) + "\n", encoding="utf-8")
            os.replace(temporary, self.path)

    @staticmethod
    def classify(code: str | None) -> str:
        prefix = (code or "").split(".")[0]
        return {
            "AUTH": "authentication",
            "PRIVACY": "privacy",
            "POLICY": "policy",
            "TOOL": "tools",
            "TASK": "tasks",
            "RAG": "knowledge",
            "MEMORY": "memory",
            "MODEL": "model",
            "SYSTEM": "runtime",
        }.get(prefix, "runtime")
