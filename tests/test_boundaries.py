import asyncio
import json
from pathlib import Path

import httpx
import pytest
from adam.api.app import create_app
from adam.core.config import ModelConfig, Settings
from adam.core.runtime import ChatRequest, Runtime
from adam.models.base import Message
from adam.models.llama_cpp import LlamaCppProvider
from auth_client import OwnerClient as TestClient
from starlette.websockets import WebSocketDisconnect
from test_text_runtime import provider


def test_tokenizer_adapter_and_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/apply-template":
            assert json.loads(request.content)["messages"][0]["role"] == "user"
            return httpx.Response(200, json={"prompt": "formatted"})
        assert request.url.path == "/tokenize"
        assert json.loads(request.content)["content"] == "formatted"
        return httpx.Response(200, json={"tokens": [1, 2, 3]})

    adapter = LlamaCppProvider(ModelConfig(), httpx.MockTransport(handler))
    messages = [Message(role="user", content="hello")]
    assert asyncio.run(adapter.count_tokens(messages)) == 35
    assert asyncio.run(provider().count_tokens(messages)) > 35


def test_busy_rejection_does_not_unlock_running_turn(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = Runtime(Settings(data_dir=tmp_path), provider())
        stream = runtime.stream(ChatRequest(text="first"))
        first = await anext(stream)
        result = await runtime.chat(ChatRequest(text="second", session_id=first.session_id))
        assert result.payload["error"]["code"] == "SESSION.BUSY"
        assert runtime.sessions.sessions[first.session_id].busy
        await stream.aclose()
        assert not runtime.sessions.sessions[first.session_id].busy

    asyncio.run(run())


def test_trace_failure_cannot_report_success(tmp_path: Path, monkeypatch) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider())

    def fail(event) -> None:
        raise OSError("secret filesystem detail")

    monkeypatch.setattr(runtime.traces, "record", fail)
    result = asyncio.run(runtime.chat(ChatRequest(text="hello")))
    assert result.event_type == "agent.error"
    assert result.payload["error"]["code"] == "SYSTEM.TRACE_UNAVAILABLE"
    assert "secret filesystem" not in result.model_dump_json()
    assert not runtime.sessions.sessions[result.session_id].messages


def test_foreign_websocket_origin_rejected(tmp_path: Path) -> None:
    with TestClient(
        create_app(Settings(data_dir=tmp_path), provider()), base_url="http://localhost"
    ) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "ws://localhost:8765/ws/chat", headers={"Origin": "https://evil.example"}
            ):
                pass


def test_model_identity_mismatch(tmp_path: Path) -> None:
    adapter = provider(model_id="actual")
    adapter.config.model_id = "wrong"
    result = asyncio.run(Runtime(Settings(data_dir=tmp_path), adapter).chat(ChatRequest(text="hi")))
    assert result.payload["error"]["code"] == "MODEL.IDENTITY_MISMATCH"
