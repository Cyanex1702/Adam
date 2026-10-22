import asyncio
from pathlib import Path

from adam.core.config import Settings
from adam.core.runtime import ChatRequest, Runtime
from test_memory import command
from test_text_runtime import provider


def test_two_runtimes_share_session_lock_and_cancel_releases(tmp_path: Path) -> None:
    async def run() -> None:
        one = Runtime(Settings(data_dir=tmp_path), provider())
        two = Runtime(Settings(data_dir=tmp_path), provider())
        stream = one.stream(ChatRequest(text="first"))
        started = await anext(stream)
        sid = started.session_id
        assert sid is not None
        other = await two.chat(ChatRequest(text="second", session_id=sid))
        assert other.payload["error"]["code"] == "SESSION.BUSY"
        assert not two.sessions.close(sid)
        await stream.aclose()
        assert one.store.get(sid)["lease_owner"] is None
        assert (
            await two.chat(ChatRequest(text="resumed", session_id=sid))
        ).event_type == "agent.completed"

    asyncio.run(run())


def test_cache_eviction_preserves_archive(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path, max_sessions=1), provider("offline"))
    first = command(runtime, "/remember semantic color = blue")
    command(runtime, "/show memory missing")
    assert len(runtime.sessions.sessions) == 1
    command(runtime, "/show memory color", first.session_id)
    assert len(runtime.sessions.sessions) == 1
    assert len(runtime.store.list_sessions()) == 2


def test_memory_change_during_generation_does_not_commit_stale_turn(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = Runtime(Settings(data_dir=tmp_path), provider())
        stream = runtime.stream(ChatRequest(text="tell me about editor"))
        started = await anext(stream)
        update = await runtime.chat(ChatRequest(text="/remember preference editor = Cursor"))
        assert update.event_type == "agent.completed"
        events = [event async for event in stream]
        assert events[-1].payload["error"]["code"] == "MEMORY.CONTEXT_CHANGED"
        assert started.session_id is not None
        assert runtime.store.history(started.session_id) == []

    asyncio.run(run())
