from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal

from adam.compute.contracts import ComputeError
from adam.core.contracts import Contract, SessionId, TraceId, new_id, utc_now
from adam.core.privacy import contains_secret
from adam.memory.service import (
    Evidence,
    MemoryCommand,
    MemoryCommandError,
    MemoryRecord,
    MemoryService,
    normalize,
)


class Candidate(Contract):
    candidate_id: str
    key: str
    content: str
    type: Literal["semantic", "preference"]
    status: Literal["CANDIDATE", "ACCEPTED", "REJECTED"] = "CANDIDATE"
    epistemic_status: Literal["REPORTED", "UNCERTAIN"] = "REPORTED"
    privacy: Literal["PERSONAL"] = "PERSONAL"
    evidence: Evidence
    memory_id: str | None = None


class ConsolidationReport(Contract):
    merged: int = 0
    updated: int = 0
    summaries: int = 0
    candidates: int = 0


class ConsolidationService:
    def __init__(self, memories: MemoryService) -> None:
        self.memories = memories
        self.store = memories.store
        self.status = "STOPPED"
        self.last_report: ConsolidationReport | None = None
        self._stop: asyncio.Event | None = None
        self._worker: asyncio.Task[None] | None = None
        self.background_runner: (
            Callable[[Callable[[], ConsolidationReport]], Awaitable[ConsolidationReport]] | None
        ) = None

    def scan_candidates(self, db: sqlite3.Connection) -> int:
        row = db.execute(
            "SELECT value FROM runtime_metadata WHERE key='candidate_through'"
        ).fetchone()
        cursor = int(row[0]) if row else 0
        turns = db.execute(
            "SELECT * FROM turns WHERE turn_id>? ORDER BY turn_id LIMIT 1000", (cursor,)
        ).fetchall()
        count = 0
        for turn in turns:
            if turn["model_id"] == "grounded_source_service":
                continue
            text = turn["user_text"].strip()
            if text.startswith("/") or contains_secret(text):
                continue
            match = re.fullmatch(r"My (.{1,60}?) (?:is|are) (.{1,1600})", text, re.IGNORECASE)
            prefer = re.fullmatch(r"I prefer (.{1,1600})", text, re.IGNORECASE)
            if not match and not prefer:
                continue
            key = match.group(1) if match else "preference " + normalize(text)[:80]
            uncertain = bool(
                re.search(r"\b(might|may|maybe|possibly|perhaps|shayad)\b", text, re.IGNORECASE)
            )
            candidate = Candidate(
                candidate_id=new_id(),
                key=key,
                content=text,
                type="preference" if prefer else "semantic",
                epistemic_status="UNCERTAIN" if uncertain else "REPORTED",
                evidence=Evidence(
                    source="conversation_candidate_not_confirmed",
                    session_id=SessionId(turn["session_id"]),
                    trace_id=TraceId(turn["trace_id"]),
                    timestamp=datetime.fromisoformat(turn["created_at"]),
                ),
            )
            result = db.execute(
                "INSERT OR IGNORE INTO memory_candidates VALUES (?,?,?,?)",
                (
                    candidate.candidate_id,
                    turn["trace_id"],
                    candidate.status,
                    candidate.model_dump_json(),
                ),
            )
            count += result.rowcount
        if turns:
            db.execute(
                "INSERT INTO runtime_metadata VALUES ('candidate_through',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(turns[-1]["turn_id"]),),
            )
        return count

    def candidates(self, db: sqlite3.Connection | None = None) -> list[Candidate]:
        if db is None:
            with self.store.connect() as connection:
                return self.candidates(connection)
        return [
            Candidate.model_validate_json(row[0])
            for row in db.execute(
                "SELECT record FROM memory_candidates WHERE status='CANDIDATE' LIMIT 100"
            )
        ]

    def consolidate_in(self, db: sqlite3.Connection, now: datetime) -> ConsolidationReport:
        report = ConsolidationReport(candidates=self.scan_candidates(db))
        records = [
            MemoryRecord.model_validate_json(row[0])
            for row in db.execute("SELECT record FROM memories")
        ]
        groups: dict[tuple[str, str, str, str, str], MemoryRecord] = {}
        # Narrow deterministic aliases (e.g. VS Code/vscode), never semantic LLM guesses.
        for item in sorted(records, key=lambda record: record.created_at):
            if item.generated_summary:
                continue
            key = (
                normalize(item.key),
                normalize(item.content),
                item.type,
                item.status,
                item.privacy,
            )
            kept = groups.get(key)
            if kept is None:
                groups[key] = item
                continue
            kept.provenance += [
                source for source in item.provenance if source not in kept.provenance
            ]
            kept.pinned = kept.pinned or item.pinned
            kept.retention = "PINNED" if kept.pinned else kept.retention
            kept.importance = max(kept.importance, item.importance)
            db.execute("DELETE FROM memories WHERE memory_id=?", (item.memory_id,))
            db.execute(
                "UPDATE sessions SET memory_focus=? WHERE memory_focus=?",
                (kept.memory_id, item.memory_id),
            )
            self.memories.save(db, kept)
            report.merged += 1
        for item in groups.values():
            previous = item.model_dump_json()
            age = max(0, (now.date() - (item.last_accessed or item.created_at).date()).days)
            item.retrieval_priority = round(
                item.importance if item.pinned else item.importance * 0.5 ** (age / 180), 6
            )
            item.decay_as_of = now.date().isoformat()
            if item.pinned:
                item.tier = "HOT"
                item.retention = "PINNED"
                item.archive_reason = None
            elif item.archive_reason == "owner":
                item.tier = "COLD"
            elif age >= 30 and item.importance < 0.4:
                item.tier = "COLD"
                item.retention = "ARCHIVAL"
                item.archive_reason = "low_importance"
            else:
                item.tier = "WARM" if age >= 7 or item.status != "CURRENT" else "HOT"
            if previous != item.model_dump_json():
                self.memories.save(db, item)
                report.updated += 1
        self._summarize(db, report)
        if report.updated or report.merged or report.summaries:
            self.store.bump_memory_revision(db)
        return report

    def _summarize(self, db: sqlite3.Connection, report: ConsolidationReport) -> None:
        records = [
            MemoryRecord.model_validate_json(row[0])
            for row in db.execute("SELECT record FROM memories")
        ]
        for kind in ["project", "goal"]:
            sources = sorted(
                [
                    item
                    for item in records
                    if item.type == kind
                    and item.status == "CURRENT"
                    and item.tier != "COLD"
                    and not item.generated_summary
                    and "owner" in item.allowed_audiences
                    and item.subjects == ["owner"]
                ],
                key=lambda item: item.key,
            )
            existing = next(
                (
                    item
                    for item in records
                    if item.generated_summary and item.key == "summary/" + kind
                ),
                None,
            )
            if len(sources) < 2:
                if existing:
                    db.execute("DELETE FROM memories WHERE memory_id=?", (existing.memory_id,))
                    report.summaries += 1
                continue
            content = (
                "Reported "
                + kind
                + " summary: "
                + "; ".join(f"{item.key}: {item.content}" for item in sources)
            )
            # Include complete statements only; avoid a cutoff dropping uncertainty/negation.
            while len(content) > 2000 and len(sources) > 1:
                sources.pop()
                content = (
                    "Reported "
                    + kind
                    + " summary: "
                    + "; ".join(f"{item.key}: {item.content}" for item in sources)
                )
            if len(content) > 2000:
                continue
            privacy_rank = {"PUBLIC": 0, "PERSONAL": 1, "PRIVATE": 2, "CONFIDENTIAL": 3}
            privacy = max((item.privacy for item in sources), key=lambda p: privacy_rank[p])
            provenance = [source for item in sources for source in item.provenance]
            summary = MemoryRecord(
                memory_id=existing.memory_id if existing else new_id(),
                key="summary/" + kind,
                content=content,
                type="semantic",
                privacy=privacy,
                created_at=existing.created_at
                if existing
                else max(item.created_at for item in sources),
                valid_from=max(item.valid_from for item in sources),
                importance=max(item.importance for item in sources),
                confidence=min(item.confidence for item in sources),
                provenance=provenance,
                generated_summary=True,
                summary_of=[item.memory_id for item in sources],
            )
            if existing:
                # Derived text updates do not reset access, pinning, or owner archival choices.
                summary = existing.model_copy(
                    update={
                        "content": summary.content,
                        "privacy": summary.privacy,
                        "valid_from": summary.valid_from,
                        "importance": summary.importance,
                        "confidence": summary.confidence,
                        "provenance": summary.provenance,
                        "summary_of": summary.summary_of,
                    }
                )
            if existing is None or existing.model_dump_json() != summary.model_dump_json():
                self.memories.save(db, summary)
                report.summaries += 1

    def consolidate(self, now: datetime | None = None) -> ConsolidationReport:
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self.consolidate_in(db, now or utc_now())

    def execute(
        self,
        db: sqlite3.Connection,
        command: MemoryCommand,
        session_id: SessionId,
        trace_id: TraceId,
    ) -> tuple[str, dict[str, Any]]:
        action, argument = command.action, command.argument
        if action == "consolidate":
            report = self.consolidate_in(db, utc_now())
            return "Memory consolidation finished: " + report.model_dump_json(), report.model_dump()
        if action == "candidates":
            self.scan_candidates(db)
            result = [item.model_dump(mode="json") for item in self.candidates(db)]
            return json.dumps(
                result, indent=2, ensure_ascii=False
            ) if result else "No pending memory candidates.", {"candidates": result}
        if action in {"accept_candidate", "reject_candidate"}:
            row = db.execute(
                "SELECT record FROM memory_candidates WHERE candidate_id=? AND status='CANDIDATE'",
                (argument,),
            ).fetchone()
            if not row:
                raise MemoryCommandError("Pending candidate not found")
            candidate = Candidate.model_validate_json(row[0])
            candidate.status = "ACCEPTED" if action == "accept_candidate" else "REJECTED"
            if action == "accept_candidate":
                memory = self.memories.remember(
                    db,
                    key=candidate.key,
                    content=candidate.content,
                    kind=candidate.type,
                    evidence=Evidence(
                        source="owner_confirmed_candidate",
                        session_id=session_id,
                        trace_id=trace_id,
                        timestamp=utc_now(),
                    ),
                )
                memory.provenance.append(candidate.evidence)
                self.memories.save(db, memory)
                candidate.memory_id = memory.memory_id
                db.execute(
                    "UPDATE sessions SET memory_focus=? WHERE session_id=?",
                    (memory.memory_id, session_id),
                )
            db.execute(
                "UPDATE memory_candidates SET status=?,record=? WHERE candidate_id=?",
                (candidate.status, candidate.model_dump_json(), candidate.candidate_id),
            )
            return "Candidate " + candidate.status.lower() + ".", {
                "candidate": candidate.model_dump(mode="json")
            }
        if action in {"archive", "pin", "unpin"}:
            memory = self.memories._select(db, argument, session_id)
            if memory.generated_summary:
                raise MemoryCommandError(
                    "Manage source memories; derived summaries are refreshed automatically"
                )
            if action == "archive":
                if memory.pinned:
                    raise MemoryCommandError("Unpin the memory before archiving it")
                memory.tier, memory.retention, memory.archive_reason = "COLD", "ARCHIVAL", "owner"
            else:
                memory.pinned = action == "pin"
                memory.retention = "PINNED" if memory.pinned else "LONG_TERM"
                if memory.pinned:
                    memory.tier, memory.archive_reason = "HOT", None
            self.memories.save(db, memory)
            return f"Memory {action} saved for {memory.memory_id}.", {
                "memory": memory.model_dump(mode="json")
            }
        raise MemoryCommandError("Unsupported consolidation command")

    async def start(self, interval: float) -> None:
        if self._worker:
            return
        self._stop = asyncio.Event()

        async def loop() -> None:
            assert self._stop is not None
            while not self._stop.is_set():
                try:
                    self.last_report = (
                        await self.background_runner(self.consolidate)
                        if self.background_runner
                        else await asyncio.to_thread(self.consolidate)
                    )
                    self.status = "RUNNING"
                except ComputeError:
                    self.status = "PAUSED_RESOURCE_PRESSURE"
                except (sqlite3.Error, ValueError, OSError):
                    self.status = "DEGRADED"
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=interval)
                except TimeoutError:
                    pass

        self._worker = asyncio.create_task(loop())

    async def stop(self) -> None:
        if self._stop:
            self._stop.set()
        if self._worker:
            await self._worker
        self._worker = None
        self.status = "STOPPED"
