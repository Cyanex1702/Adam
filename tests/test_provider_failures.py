import asyncio
import json
from pathlib import Path

import httpx
import pytest
from adam.core.config import ModelConfig, Settings
from adam.core.runtime import ChatRequest, Runtime
from adam.models.llama_cpp import LlamaCppProvider


@pytest.mark.parametrize(
    "mode,code",
    [
        ("limit", "MODEL.RESPONSE_LIMIT"),
        ("timeout", "MODEL.TIMEOUT"),
        ("empty", "MODEL.PROTOCOL_ERROR"),
    ],
)
def test_generation_failure_paths(tmp_path: Path, mode: str, code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen3-8b"}]})
        if request.url.path in {"/apply-template", "/tokenize"}:
            return httpx.Response(404)
        if mode == "timeout":
            raise httpx.ReadTimeout("private provider detail")
        choice = {"delta": {"reasoning_content": "HIDDEN_REASONING"}}
        if mode == "limit":
            choice["delta"]["content"] = "partial"
            choice["finish_reason"] = "length"
        data = "data: " + json.dumps({"choices": [choice]}) + "\n\ndata: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=data)

    adapter = LlamaCppProvider(ModelConfig(), httpx.MockTransport(handler))
    runtime = Runtime(Settings(data_dir=tmp_path), adapter)
    result = asyncio.run(runtime.chat(ChatRequest(text="hello")))
    assert result.event_type == "agent.error"
    assert result.payload["error"]["code"] == code
    assert "private provider detail" not in result.model_dump_json()
    assert "HIDDEN_REASONING" not in (tmp_path / "audit" / "turns.jsonl").read_text()


def test_server_context_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200)
        return httpx.Response(200, json={"data": [{"id": "qwen3-8b", "meta": {"n_ctx": 512}}]})

    adapter = LlamaCppProvider(ModelConfig(), httpx.MockTransport(handler))
    health = asyncio.run(adapter.health_check())
    assert health.status == "DEGRADED"
    assert health.reason == "MODEL.CONTEXT_MISMATCH"
