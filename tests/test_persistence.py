import asyncio
import sqlite3
from pathlib import Path

import pytest
from adam.core.config import Settings
from adam.core.contracts import SessionId, TraceId
from adam.core.runtime import ChatRequest, Runtime
from adam.core.storage import ConversationStore
from test_text_runtime import provider


def test_restart_history_and_resume(tmp_path: Path) -> None:
    first = Runtime(Settings(data_dir=tmp_path), provider())
    event = asyncio.run(first.chat(ChatRequest(text="My project is River")))
    sid = event.session_id
    assert sid is not None
    second = Runtime(Settings(data_dir=tmp_path), provider(model_id="replacement"))
    assert second.store.history(sid)[0]["trace_id"] == event.trace_id
    assert (
        asyncio.run(second.chat(ChatRequest(text="continue", session_id=sid))).event_type
        == "agent.completed"
    )
    assert second.sessions.sessions[sid].messages[0].content == "My project is River"
    assert second.sessions.close(sid)
    assert second.store.history(sid)
    assert second.sessions.reopen(sid)
    assert (
        asyncio.run(second.chat(ChatRequest(text="resumed", session_id=sid))).event_type
        == "agent.completed"
    )


def test_failed_turn_transaction_rolls_back(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path / "runtime.sqlite3")
    sid = SessionId("test")
    store.create(sid)
    with store.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_update BEFORE UPDATE ON sessions "
            "BEGIN SELECT RAISE(ABORT, 'simulated'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.append(sid, "question", "answer", TraceId("trace"), "model")
    assert store.history(sid) == []


def test_secrets_never_stored_or_sent(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider())
    for text, sensitivity in [
        ("api_key=abcdef123456789", "PERSONAL"),
        ("arbitrary-private-value", "SECRET"),
        ("-----BEGIN PRIVATE KEY-----", "PERSONAL"),
    ]:
        event = asyncio.run(runtime.chat(ChatRequest(text=text, sensitivity=sensitivity)))
        assert event.payload["error"]["code"] == "PRIVACY.SECRET_REJECTED"
        assert text not in (tmp_path / "runtime.sqlite3").read_bytes().decode(errors="ignore")
        assert text not in (tmp_path / "audit/turns.jsonl").read_text()
    sid = SessionId("safe")
    runtime.store.create(sid)
    runtime.store.append(sid, "password: raw-secret", "secret=raw-answer", TraceId("t"), "m")
    row = runtime.store.history(sid)[0]
    assert "raw-secret" not in row["user_text"]
    assert "raw-answer" not in row["assistant_text"]
