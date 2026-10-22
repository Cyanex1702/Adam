import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from adam.core.config import Settings
from adam.core.contracts import SessionId, TraceId
from adam.core.runtime import ChatRequest, Runtime
from adam.memory.service import Evidence, MemoryRecord
from test_memory import command
from test_text_runtime import provider


def seed(
    runtime: Runtime,
    name: str,
    *,
    pinned: bool = False,
    importance: float = 0.2,
    age: int = 100,
    kind: str = "semantic",
) -> MemoryRecord:
    now = datetime(2026, 10, 5, tzinfo=UTC) - timedelta(days=age)
    record = MemoryRecord(
        memory_id=name,
        key=name,
        content="reported " + name,
        type=kind,
        created_at=now,
        valid_from=now,
        pinned=pinned,
        importance=importance,
        provenance=[Evidence(session_id=SessionId("seed"), trace_id=TraceId(name), timestamp=now)],
    )
    with runtime.store.connect() as db:
        runtime.memories.save(db, record)
    return record


def test_archive_decay_pins_and_idempotence(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    now = datetime(2026, 10, 5, tzinfo=UTC)
    seed(runtime, "low-value")
    seed(runtime, "meaningful", importance=0.9, age=1000)
    seed(runtime, "pinned", pinned=True, age=2000)
    first = runtime.consolidation.consolidate(now)
    assert first.updated == 3
    visible = {item.key: item for item in runtime.memories.search()}
    assert "low-value" not in visible
    assert visible["pinned"].tier == "HOT" and visible["pinned"].valid_until is None
    assert visible["meaningful"].tier == "WARM"
    archived = runtime.memories.search("low-value", archived=True)[0]
    assert archived.tier == "COLD" and archived.retrieval_priority < archived.importance
    with runtime.store.connect() as db:
        before = [row[0] for row in db.execute("SELECT record FROM memories ORDER BY memory_id")]
    second = runtime.consolidation.consolidate(now)
    assert second.updated == second.merged == second.summaries == 0
    with runtime.store.connect() as db:
        assert before == [
            row[0] for row in db.execute("SELECT record FROM memories ORDER BY memory_id")
        ]


def test_project_summary_privacy_and_forget(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    first = command(runtime, "/remember project framework = ADAM")
    command(runtime, "/remember --private project language = Python")
    now = datetime(2026, 10, 5, tzinfo=UTC)
    assert runtime.consolidation.consolidate(now).summaries == 1
    summary = next(item for item in runtime.memories.search() if item.generated_summary)
    assert summary.privacy == "PRIVATE" and len(summary.summary_of) == 2
    assert "ADAM" in summary.content and "Python" in summary.content
    assert runtime.consolidation.consolidate(now).summaries == 0
    command(runtime, "/forget framework", first.session_id)
    assert not any(item.generated_summary for item in runtime.memories.search())


def test_candidates_explicit_acceptance_and_chatter(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider())
    event = asyncio.run(runtime.chat(ChatRequest(text="My editor is VS Code")))
    assert event.event_type == "agent.completed"
    asyncio.run(runtime.chat(ChatRequest(text="hello")))
    assert runtime.consolidation.consolidate().candidates == 1
    candidates = runtime.consolidation.candidates()
    assert len(candidates) == 1 and not runtime.memories.search()
    command(runtime, "/accept " + candidates[0].candidate_id)
    remembered = runtime.memories.search("editor")[0]
    assert len(remembered.provenance) == 2
    assert remembered.provenance[1].trace_id == event.trace_id
    assert runtime.consolidation.consolidate().candidates == 0
    assert runtime.consolidation.candidates() == []
    command(runtime, "/archive editor")
    assert not runtime.memories.search("editor")
    assert runtime.memories.search("editor", archived=True)


def test_background_worker_runs_and_stops(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
        await runtime.consolidation.start(10)
        for _ in range(100):
            if runtime.consolidation.last_report is not None:
                break
            await asyncio.sleep(0.02)
        assert runtime.consolidation.status == "RUNNING"
        await runtime.consolidation.stop()
        assert runtime.consolidation.status == "STOPPED"

    asyncio.run(run())


def test_consolidation_merges_duplicate_preference_evidence(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    original = seed(runtime, "editor")
    original.type, original.status, original.content = "preference", "POSSIBLE", "VS Code"
    duplicate = original.model_copy(
        update={
            "memory_id": "duplicate",
            "content": "vscode",
            "pinned": True,
            "provenance": [
                original.provenance[0].model_copy(update={"trace_id": TraceId("another")})
            ],
        }
    )
    with runtime.store.connect() as db:
        runtime.memories.save(db, original)
        runtime.memories.save(db, duplicate)
    report = runtime.consolidation.consolidate()
    assert report.merged == 1
    records = runtime.memories.search("editor", historical=True, archived=True)
    assert len(records) == 1 and records[0].pinned and len(records[0].provenance) == 2


def test_archive_immediately_invalidates_derived_summary(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    command(runtime, "/remember project framework = ADAM")
    command(runtime, "/remember project language = Python")
    runtime.consolidation.consolidate()
    assert any(item.generated_summary for item in runtime.memories.search())
    command(runtime, "/archive language")
    assert not runtime.memories.search("language")
    assert runtime.memories.search("language", archived=True)
