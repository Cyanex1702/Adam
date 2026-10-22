import asyncio
import json

from adam.api.app import create_app
from adam.core.config import Settings
from adam.core.contracts import EventEnvelope, TraceId, new_id
from adam.core.privacy import register_secret
from adam.core.runtime import ChatRequest, Runtime
from adam.observability.service import TraceConfig, TraceService
from adam.security.policy import Principal
from adam.tools.contracts import ToolCall
from fastapi.testclient import TestClient
from test_text_runtime import provider


def test_trace_conversation_memory_and_action_metadata_only(tmp_path):
    runtime = Runtime(Settings(data_dir=tmp_path), provider())
    private = "unregistered private marker conversational grapefruit"
    try:
        event = asyncio.run(runtime.chat(ChatRequest(text=private)))
        points = runtime.traces.list(str(event.trace_id))
        assert {item.subsystem for item in points} >= {"runtime", "model", "memory", "context"}
        assert all(item.duration_ms is None or item.duration_ms >= 0 for item in points)
        assert any(item.metrics.get("input_tokens", 0) > 0 for item in points)
        assert private not in json.dumps([item.model_dump() for item in points])
        memory = asyncio.run(
            runtime.chat(ChatRequest(text="/remember preference editor = Synthetic Editor"))
        )
        assert any(
            point.subsystem == "memory" for point in runtime.traces.list(str(memory.trace_id))
        )
        action = runtime.actions.preview(
            ToolCall(name="notes.create", arguments={"path": "private-note.txt", "text": private}),
            Principal(),
        )
        runtime.actions.approve(action.action_id, action.digest, Principal(elevated=True))
        runtime.actions.execute(action.action_id, Principal(elevated=True))
        timeline = runtime.traces.list(action.trace_id)
        assert [point.status for point in timeline] == [
            "PREVIEW",
            "APPROVED",
            "RUNNING",
            "VERIFIED",
        ]
        serialized = json.dumps([point.model_dump() for point in timeline])
        assert private not in serialized and "private-note.txt" not in serialized
        assert private.encode() not in runtime.traces.database.read_bytes()
    finally:
        runtime.retrieval.close()


def test_trace_redaction_levels_retention_and_closed_handles(tmp_path):
    service = TraceService(tmp_path, TraceConfig(max_events=100))
    secret = "synthetic-trace-secret-marker-632"
    register_secret(secret)
    service.emit(new_id(), "model", secret, "SUCCEEDED")
    assert not service.database.exists()
    for index in range(105):
        service.emit(new_id(), "runtime", "bounded", "SUCCEEDED", metrics={"index": index})
    assert len(service.list(limit=1000)) == 100
    with service.connect() as db:
        db.execute("UPDATE events SET timestamp=0")
    assert service.list() == []
    relocated = service.database.with_suffix(".closed")
    service.database.rename(relocated)
    relocated.rename(service.database)
    error_only = TraceService(tmp_path / "errors", TraceConfig(level="ERROR"))
    error_only.emit(new_id(), "model", "generation", "SUCCEEDED")
    assert not error_only.database.exists()
    error_only.emit(new_id(), "model", "generation", "FAILED", error_code="MODEL.UNAVAILABLE")
    assert len(error_only.list()) == 1
    off = TraceService(tmp_path / "off", TraceConfig(level="OFF"))
    off.record(
        EventEnvelope(
            event_type="agent.turn_trace", trace_id=TraceId(new_id()), payload={"status": "FAILED"}
        )
    )
    assert not off.path.exists()


def test_console_and_inspectors_require_fresh_owner_authorization(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), provider())
    password = "synthetic-console-owner-passphrase"
    app.state.auth.initialize(password)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/console")
        assert response.status_code == 200
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert client.get("/console.js").status_code == 200
        assert client.get("/developer/health").status_code == 401
        client.post("/auth/login", json={"password": password})
        assert client.get("/developer/health").status_code == 403
        client.post("/auth/elevate", json={"password": password})
        assert client.get("/developer/health").json()["resources"]["vram_bytes"] is None
        event = client.post("/chat", json={"text": "private query marker"}).json()
        detail = client.get(f"/developer/traces/{event['trace_id']}")
        assert detail.status_code == 200
        assert "private query marker" not in detail.text
        failed = client.post("/tools/preview", json={"name": "shell.exec"}).json()
        classified = client.get(f"/developer/traces/{failed['trace_id']}").json()
        assert classified["error_subsystems"] == ["tools"]
        assert client.get("/developer/memory").status_code == 200
        with app.state.auth.connect() as db:
            db.execute("UPDATE tokens SET elevated_until=0")
        assert client.get("/developer/traces").status_code == 403
        client.post("/auth/switch", json={"mode": "guest"})
        assert client.get("/developer/health").status_code == 403
