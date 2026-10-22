import asyncio
import json

import httpx
import pytest
from adam.api.app import create_app
from adam.core.config import ModelConfig, Settings
from adam.core.contracts import new_id
from adam.core.privacy import register_secret
from adam.core.runtime import ChatRequest, Runtime
from adam.models.llama_cpp import LlamaCppProvider
from adam.security.auth import AuthError, AuthManager
from adam.security.request import AUTHORITY
from fastapi.testclient import TestClient
from test_auth import PASSWORD
from test_text_runtime import provider


def test_anonymous_rate_limit_and_credentials_header_fail_closed(tmp_path):
    auth = AuthManager(tmp_path / "authority")
    tokens = [auth.issue("guest") for _ in range(10)]
    assert len({auth.resolve(token).profile_id for token in tokens}) == 10
    with pytest.raises(AuthError, match="RATE_LIMITED"):
        auth.issue("demo")
    app = create_app(Settings(data_dir=tmp_path / "api"), provider())
    app.state.auth.initialize(PASSWORD)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.post("/auth/login", json={"password": PASSWORD}).status_code == 200
        assert client.get("/auth/status").status_code == 200
        assert (
            client.get("/auth/status", headers={"Authorization": "Bearer forged"}).status_code
            == 401
        )
        assert (
            client.post(
                "/auth/session", json={"mode": "demo", "profile_id": "../../owner"}
            ).status_code
            == 422
        )


def test_revocation_during_generation_prevents_committed_turn(tmp_path):
    async def run():
        auth = AuthManager(tmp_path)
        auth.initialize(PASSWORD)
        token = auth.issue("owner", PASSWORD)
        runtime = Runtime(Settings(data_dir=tmp_path), provider())

        def verify():
            auth.resolve(token)

        marker = AUTHORITY.set(verify)
        try:
            stream = runtime.stream(ChatRequest(text="Hello"))
            started = await anext(stream)
            auth.revoke(token)
            events = [event async for event in stream]
            assert events[-1].event_type == "agent.error"
            assert all(event.event_type != "agent.completed" for event in events)
            assert runtime.store.history(started.session_id) == []
        finally:
            AUTHORITY.reset(marker)

    asyncio.run(run())


def test_known_secret_split_across_provider_tokens_does_not_leak_prefix(tmp_path):
    value = "EdgeVaultSecret-" + new_id()
    register_secret(value)

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen3-8b"}]})
        if request.url.path in {"/apply-template", "/tokenize"}:
            return httpx.Response(404)
        chunks = ["Ordinary prefix. ", value[:7], value[7:18], value[18:]]
        stream = "".join(
            "data: " + json.dumps({"choices": [{"delta": {"content": part}}]}) + "\n\n"
            for part in chunks
        )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=stream + "data: [DONE]\n\n"
        )

    runtime = Runtime(
        Settings(data_dir=tmp_path), LlamaCppProvider(ModelConfig(), httpx.MockTransport(handler))
    )

    async def run():
        return [event async for event in runtime.stream(ChatRequest(text="Hello"))]

    events = asyncio.run(run())
    assert events[-1].payload["error"]["code"] == "PRIVACY.SECRET_OUTPUT"
    visible = "".join(
        event.payload.get("text", "") for event in events if event.event_type == "agent.token"
    )
    assert visible == "Ordinary prefix. "
    assert runtime.store.history(events[0].session_id) == []
