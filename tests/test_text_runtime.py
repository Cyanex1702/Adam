import asyncio
import json
from pathlib import Path

import httpx
from adam.api.app import create_app
from adam.core.config import ModelConfig, Settings
from adam.core.contracts import TraceId
from adam.core.runtime import ChatRequest, Runtime
from adam.models.base import Message
from adam.models.llama_cpp import LlamaCppProvider
from auth_client import OwnerClient as TestClient


def provider(mode: str = "ok", model_id: str = "qwen3-8b") -> LlamaCppProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/apply-template", "/tokenize"}:
            return httpx.Response(404)
        if request.url.path == "/health":
            return httpx.Response(503 if mode == "offline" else 200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": model_id}]})
        if mode == "malformed":
            data = "data: {bad json}\n\n"
        elif mode == "truncated":
            data = 'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        else:
            data = "".join(
                "data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n\n"
                for text in ["Hello ", "دنیا"]
            )
            data += "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=data)

    return LlamaCppProvider(ModelConfig(model_id=model_id), httpx.MockTransport(handler))


def test_api_stream_and_session(tmp_path: Path) -> None:
    with TestClient(
        create_app(Settings(data_dir=tmp_path), provider()), base_url="http://localhost"
    ) as client:
        assert client.get("/health").json()["status"] == "HEALTHY"
        with client.websocket_connect("ws://localhost:8765/ws/chat") as socket:
            socket.send_json({"text": "Hello دنیا"})
            events = [socket.receive_json() for _ in range(4)]
            assert [e["event_type"] for e in events] == [
                "agent.started",
                "agent.token",
                "agent.token",
                "agent.completed",
            ]
            assert events[-1]["payload"]["text"] == "Hello دنیا"
        session = events[-1]["session_id"]
        assert (
            client.post("/chat", json={"session_id": session, "text": "again"}).status_code == 200
        )
        assert client.delete(f"/sessions/{session}").json()["closed"]
        assert (
            client.post("/chat", json={"session_id": session, "text": "again"}).status_code == 503
        )
    trace = (tmp_path / "audit" / "turns.jsonl").read_text()
    assert "دنیا" not in trace
    assert "qwen3-8b" in trace


def test_failures_no_false_completion(tmp_path: Path) -> None:
    for mode, code in [
        ("offline", "MODEL.UNAVAILABLE"),
        ("malformed", "MODEL.PROTOCOL_ERROR"),
        ("truncated", "MODEL.PROTOCOL_ERROR"),
    ]:
        runtime = Runtime(Settings(data_dir=tmp_path), provider(mode))
        result = asyncio.run(runtime.chat(ChatRequest(text="do something")))
        assert result.event_type == "agent.error"
        assert result.payload["error"]["code"] == code
        assert not runtime.sessions.sessions[result.session_id].messages


def test_model_swappable(tmp_path: Path) -> None:
    for name in ["qwen3-8b", "another-model"]:
        runtime = Runtime(Settings(data_dir=tmp_path), provider(model_id=name))
        result = asyncio.run(runtime.chat(ChatRequest(text="hello")))
        assert result.payload["model"]["model_id"] == name
        assert result.event_type == "agent.completed"


def test_context_and_validation(tmp_path: Path) -> None:
    runtime = Runtime(Settings(data_dir=tmp_path), provider())
    result = asyncio.run(runtime.chat(ChatRequest(text="x" * 10000)))
    assert result.payload["error"]["code"] == "MODEL.CONTEXT_LIMIT"
    with TestClient(
        create_app(Settings(data_dir=tmp_path), provider()), base_url="http://localhost"
    ) as client:
        invalid = client.post("/chat", json={"text": "secret-value", "role": "owner"})
        assert invalid.status_code == 422
        assert "secret-value" not in invalid.text
        assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400


def test_cancellation_releases_session(tmp_path: Path) -> None:
    async def run() -> None:
        runtime = Runtime(Settings(data_dir=tmp_path), provider())
        stream = runtime.stream(ChatRequest(text="hello"))
        first = await anext(stream)
        await stream.aclose()
        assert not runtime.sessions.sessions[first.session_id].busy

    asyncio.run(run())


def test_provider_generate() -> None:
    assert (
        asyncio.run(provider().generate([Message(role="user", content="Hi")], TraceId("test")))
        == "Hello دنیا"
    )
