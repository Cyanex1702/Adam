import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from adam.core.config import Settings
from adam.core.contracts import SessionId, TraceId, new_id, utc_now
from adam.core.migrations import MIGRATIONS, migrate
from adam.core.runtime import ChatRequest, Runtime
from adam.core.storage import ConversationStore
from adam.evals.suite import ProbeProvider
from adam.intelligence.service import Goal, Intelligence, Link, PersonalError
from adam.memory.service import Evidence, MemoryCommand, MemoryService
from adam.security.policy import Principal


@pytest.fixture
def personal(tmp_path):
    memories = MemoryService(ConversationStore(tmp_path / "runtime.sqlite3"))
    sid = SessionId(new_id())
    memories.store.create(sid)
    return Intelligence(memories), sid


def remember(personal, key="Cedar project", content="Cedar uses Example Studio", **kwargs):
    service, sid = personal
    when = kwargs.pop("when", utc_now())
    kind = kwargs.pop("kind", "project")
    with service.store.connect() as db:
        return service.memories.remember(
            db,
            key=key,
            content=content,
            kind=kind,
            evidence=Evidence(session_id=sid, trace_id=TraceId(new_id()), timestamp=when),
            **kwargs,
        )


def test_relationships_are_explicit_source_bound_and_explainable(personal):
    service, _ = personal
    source = remember(personal)
    assert not service.graph()["links"]
    link = service.link(
        Link(memory_id=source.memory_id, subject="Cedar", relation="uses", object="Example Studio")
    )
    assert link["source"]["provenance"] and link["source_status"] == "CURRENT"
    assert service.graph("Cedar")["links"][0]["memory_id"] == source.memory_id
    assert not service.graph("unrelated")["links"]


@pytest.mark.parametrize("label", ["Unknown company", "password=synthetic-private-value", "   "])
def test_unsupported_or_sensitive_entities_denied(personal, label):
    service, _ = personal
    source = remember(personal)
    with pytest.raises(PersonalError):
        service.link(
            Link(
                memory_id=source.memory_id, subject=label, relation="uses", object="Example Studio"
            )
        )


def test_correction_hides_stale_links_but_retains_history(personal):
    service, _ = personal
    old = remember(personal)
    service.link(
        Link(memory_id=old.memory_id, subject="Cedar", relation="uses", object="Example Studio")
    )
    remember(personal, content="Cedar now uses Fictional Editor")
    assert service.graph()["links"] == []
    assert service.graph(historical=True)["links"][0]["source_status"] == "HISTORICAL"
    assert {item["status"] for item in service.timeline()["events"]} == {"HISTORICAL", "CURRENT"}


def test_forget_cascades_to_graph(personal):
    service, sid = personal
    source = remember(personal)
    service.link(
        Link(memory_id=source.memory_id, subject="Cedar", relation="uses", object="Example Studio")
    )
    with service.store.connect() as db:
        service.memories.execute(
            db, MemoryCommand("forget", source.memory_id), sid, TraceId(new_id())
        )
    assert not service.graph(historical=True)["links"]
    with service.store.connect() as db:
        assert not db.execute("SELECT * FROM personal_links").fetchall()


def test_retracted_and_subject_restricted_evidence_unavailable(personal):
    service, _ = personal
    source = remember(personal)
    for update in [{"subjects": ["someone_else"]}, {"retracted": True}]:
        with service.store.connect() as db:
            service.memories.save(db, source.model_copy(update=update))
        with pytest.raises(PersonalError):
            service.evidence(source.memory_id)
        assert not service.timeline()["events"]


def test_historical_time_queries_and_invalid_ranges(personal):
    service, _ = personal
    now = utc_now()
    remember(personal, when=now - timedelta(days=3))
    remember(personal, content="Cedar uses Another Editor", when=now - timedelta(days=1))
    old = service.timeline(as_of=now - timedelta(days=2))["events"]
    assert len(old) == 1 and old[0]["content"] == "Cedar uses Example Studio"
    assert len(service.timeline(start=now - timedelta(days=2))["events"]) == 1
    with pytest.raises(PersonalError):
        service.timeline(start=now, end=now - timedelta(days=1))
    with pytest.raises(PersonalError):
        service.timeline(as_of=datetime(2026, 1, 1))


def test_goal_progress_revision_completion_and_history(personal):
    service, _ = personal
    first = service.save_goal(Goal(title="Build fictional Cedar", project="Cedar"))
    assert first["revision"] == 1
    with pytest.raises(PersonalError, match="STALE_REVISION"):
        service.save_goal(Goal(**first).model_copy(update={"revision": 0}))
    with pytest.raises(PersonalError, match="COMPLETION"):
        service.save_goal(Goal(**first).model_copy(update={"status": "COMPLETED"}))
    done = service.save_goal(
        Goal(**first).model_copy(update={"status": "COMPLETED", "progress": 100})
    )
    assert done["revision"] == 2 and len(service.goals()[0]["history"]) == 2
    assert not service.briefing()["active_goals"]


def test_goal_forgetting_removes_goal_and_progress(personal):
    service, sid = personal
    service.save_goal(Goal(title="Build fictional Cedar"))
    goal = service.goals()[0]
    with service.store.connect() as db:
        service.memories.execute(
            db, MemoryCommand("forget", goal["memory_id"]), sid, TraceId(new_id())
        )
        assert not db.execute("SELECT * FROM personal_goal_events").fetchall()
    assert service.goals() == []


def test_routine_inference_uses_distinct_dates_and_retracts(personal):
    service, sid = personal
    now = utc_now()
    sources = [
        remember(
            personal,
            key=f"review {i}",
            content="Review fictional Cedar",
            kind="episodic",
            when=now - timedelta(days=i),
        )
        for i in range(3)
    ]
    candidate = service.routines()[0]
    assert candidate["epistemic_status"] == "INFERRED" and candidate["distinct_days"] == 3
    with service.store.connect() as db:
        service.memories.execute(
            db, MemoryCommand("forget", sources[0].memory_id), sid, TraceId(new_id())
        )
    assert service.routines() == []


def test_same_day_repetition_does_not_infer_routine(personal):
    service, _ = personal
    for i in range(3):
        remember(personal, key=f"same day {i}", content="Review fictional Cedar", kind="episodic")
    assert service.routines() == []


def test_goals_due_dates_need_timezone_and_report_overdue(personal):
    service, _ = personal
    with pytest.raises(ValueError):
        Goal(title="Fictional", due=datetime(2026, 1, 1))
    goal = service.save_goal(
        Goal(title="Fictional overdue goal", due=datetime(2025, 1, 1, tzinfo=UTC))
    )
    assert service.briefing()["overdue_ids"] == [goal["id"]]


def test_schema_six_migrates_without_losing_memory(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    assert migrate(path, MIGRATIONS[:-1]) == 6
    assert migrate(path) == migrate(path) == 7


@pytest.mark.parametrize("command", ["/graph Cedar", "/timeline Cedar", "/briefing", "/goals"])
def test_personal_commands_work_without_model(tmp_path, command):
    runtime = Runtime(Settings(data_dir=tmp_path), ProbeProvider())
    try:
        event = asyncio.run(runtime.chat(ChatRequest(text=command)))
        assert (
            event.event_type == "agent.completed"
            and "Recorded personal evidence" in event.payload["text"]
        )
    finally:
        runtime.retrieval.close()


def test_guest_cannot_run_personal_commands(tmp_path):
    runtime = Runtime(
        Settings(data_dir=tmp_path), ProbeProvider(), Principal(mode="guest", person_id="guest")
    )
    try:
        event = asyncio.run(runtime.chat(ChatRequest(text="/graph Cedar")))
        assert event.event_type == "agent.error"
    finally:
        runtime.retrieval.close()
