import asyncio
from pathlib import Path

from adam.core.config import Settings
from adam.core.contracts import SessionId, TraceId
from adam.core.runtime import ChatRequest, Runtime
from adam.core.working import ContextBuilder, WorkingState, prune_stale_results
from adam.models.base import Message
from test_text_runtime import provider


def test_long_chat_bounded_summary_and_instructions(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path, recent_turns=2), provider())
    sid = SessionId("long")
    runtime.store.create(sid)
    state = WorkingState(objective="finish prototype", instructions=["Always answer in Roman Urdu"])
    runtime.store.set_working(sid, state)
    for index in range(40):
        runtime.store.append(
            sid,
            f"I might switch to Linux, note {index}",
            "Possibility only",
            TraceId(f"t{index}"),
            "old-model",
        )
    row = runtime.store.get(sid)
    assert row is not None
    assert "might switch" in row["summary"]
    assert len(row["summary"]) <= 2048 and row["summary_through"] > 0
    event = asyncio.run(runtime.chat(ChatRequest(text="continue", session_id=sid)))
    assert event.event_type == "agent.completed"
    assert event.payload["context_budget"]["input_tokens"] < 8192
    assert len(runtime.sessions.sessions[sid].messages) == 4
    restarted = Runtime(Settings(data_dir=tmp_path), provider())
    assert restarted.store.working(sid).instructions == state.instructions
    assert len(restarted.store.history(sid)) == 41


def test_pressure_preserves_current_and_pinned() -> None:
    builder = ContextBuilder(provider(), 800, 100)
    messages, budget = asyncio.run(
        builder.build(
            "identity",
            WorkingState(instructions=["Answer briefly"]),
            "old summary " * 100,
            [Message(role="user", content="old " * 500), Message(role="assistant", content="old")],
            "current instruction",
            TraceId("t"),
        )
    )
    assert budget.dropped_turns == 1
    assert messages[-1].content == "current instruction"
    assert "Answer briefly" in messages[1].content
    assert budget.input_tokens + budget.response_reserve <= budget.context_limit
    assert prune_stale_results(
        [{"task_id": "a"}, {"task_id": "b"}, {"task_id": "a", "stale": True}], "a"
    ) == [{"task_id": "a"}]
