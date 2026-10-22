import asyncio
from pathlib import Path

from adam.core.config import Settings
from adam.core.contracts import SessionId
from adam.core.runtime import ChatRequest, Runtime
from test_text_runtime import provider


def command(runtime: Runtime, text: str, sid: SessionId | None = None):
    event = asyncio.run(runtime.chat(ChatRequest(text=text, session_id=sid)))
    assert event.event_type == "agent.completed", event.model_dump()
    return event


def test_temporal_correction_provenance_restart(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    first = command(runtime, "/remember --pin preference editor = VS Code")
    mid = first.payload["result"]["memory"]["memory_id"]
    second = command(runtime, "/correct editor = Cursor", first.session_id)
    records = runtime.memories.search("editor", historical=True)
    assert len(records) == 2
    old = next(item for item in records if item.memory_id == mid)
    current = next(item for item in records if item.status == "CURRENT")
    assert old.status == "HISTORICAL" and old.valid_until == current.valid_from
    assert current.supersedes == mid and current.pinned
    restarted = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    why = command(restarted, "Why do you know that?", second.session_id)
    assert str(second.trace_id) in why.payload["text"]
    assert "explicit_owner_statement" in why.payload["text"]
    assert "Cursor" in command(restarted, "/show memory editor").payload["text"]


def test_possibility_does_not_replace_fact_and_unknown_abstains(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    command(runtime, "/remember semantic operating system = I use Windows")
    command(runtime, "/remember semantic operating system = I might switch to Linux")
    assert runtime.memories.search("operating system")[0].content == "I use Windows"
    all_records = runtime.memories.search("operating system", historical=True)
    possible = next(item for item in all_records if item.status == "POSSIBLE")
    assert possible.epistemic_status == "UNCERTAIN" and possible.confidence < 0.5
    assert "I might" not in runtime.memories.context("operating system")
    assert "do not know" in command(runtime, "/show memory birthday").payload["text"]
    assert not runtime.memories.search("birthday")


def test_duplicate_merge_and_forget_scrubs_context(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    first = command(runtime, "/remember preference editor = VS Code")
    command(runtime, "/remember --pin preference editor = vscode", first.session_id)
    memories = runtime.memories.search("editor")
    assert len(memories) == 1 and len(memories[0].provenance) == 2 and memories[0].pinned
    command(runtime, "/show memory editor", first.session_id)
    command(runtime, "Forget that.", first.session_id)
    assert runtime.memories.search("editor", historical=True, archived=True) == []
    assert first.session_id is not None
    assert all(
        "VS Code" not in row["user_text"] + row["assistant_text"]
        for row in runtime.store.history(first.session_id)
    )
    assert "VS Code" not in runtime.memories.context("editor")


def test_memory_and_turn_atomic_failure(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    with runtime.store.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_turn BEFORE INSERT ON turns "
            "BEGIN SELECT RAISE(ABORT, 'failure'); END"
        )
    event = asyncio.run(runtime.chat(ChatRequest(text="/remember preference editor = Cursor")))
    assert event.event_type == "agent.error"
    assert runtime.memories.search() == []


def test_ambiguous_correction_does_not_invent(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    event = asyncio.run(runtime.chat(ChatRequest(text="/correct missing = something")))
    assert event.payload["error"]["code"] == "MEMORY.INVALID_COMMAND"
    assert not runtime.memories.search()


def test_retraction_is_disputed_and_can_be_corrected(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    first = command(runtime, "/remember semantic nickname = River")
    rejected = command(runtime, "That is wrong.", first.session_id)
    memory = rejected.payload["result"]["memory"]
    assert memory["retracted"] and memory["confidence"] == 0
    assert memory["provenance"][-1]["source"] == "owner_retracted_statement"
    assert not runtime.memories.search("nickname")
    command(runtime, "/correct nickname = Brook", first.session_id)
    assert runtime.memories.search("nickname")[0].content == "Brook"
