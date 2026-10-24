import asyncio
import hashlib

import pytest
from adam.api.app import create_app
from adam.compute.contracts import ComputeError
from adam.compute.migration import ModelController
from adam.core.config import Settings
from adam.core.runtime import Runtime
from adam.evals.suite import ProbeProvider
from fastapi.testclient import TestClient


def controller(root):
    runtime = Runtime(Settings(data_dir=root), ProbeProvider())
    manager = ModelController(runtime.compute)
    runtime.compute.sampler = lambda: {
        "ram_available_bytes": 8 * 1024**3,
        "ram_used_percent": 40,
        "disk_free_bytes": 8 * 1024**3,
    }
    return runtime, manager


def model(folder, name="example.gguf"):
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(b"GGUF\x03\x00\x00\x00" + b"synthetic-model-fixture" * 20)
    return path


def test_discovery_requires_review_and_preserves_model_file(tmp_path):
    runtime, manager = controller(tmp_path / "data")
    path = model(tmp_path / "models")
    (path.parent / "unrelated.txt").write_text("private fixture, never read")
    result = manager.library.scan(str(path.parent))
    entry = result["entries"][0]
    assert len(result["entries"]) == 1
    assert not entry["approved"] and not result["automatic"]
    before = path.read_bytes()
    asyncio.run(manager.library.approve(entry["id"], "reasoning"))
    approved = manager.library.state.entries[entry["id"]]
    assert approved.sha256 == hashlib.sha256(before).hexdigest()
    assert approved.approved and approved.role == "reasoning"
    assert manager.active_id == "current"  # approval does not load/select a model
    assert path.read_bytes() == before
    runtime.retrieval.close()


def test_missing_changed_or_remote_models_cannot_be_approved(tmp_path):
    runtime, manager = controller(tmp_path / "data")
    path = model(tmp_path / "models")
    identifier = manager.library.scan(str(path.parent))["entries"][0]["id"]
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ComputeError, match="CHANGED_RESCAN"):
        asyncio.run(manager.library.approve(identifier, "quick"))
    for invalid in ["relative/path", "\\\\server\\models", "//server/models"]:
        with pytest.raises(ComputeError, match="LOCAL_FOLDER"):
            manager.library.scan(invalid)
    runtime.retrieval.close()


def test_approved_profile_keeps_configured_local_origin(tmp_path):
    runtime, manager = controller(tmp_path / "data")
    runtime.compute.settings.model.base_url = "http://127.0.0.1:18293"
    path = model(tmp_path / "models")
    identifier = manager.library.scan(str(path.parent))["entries"][0]["id"]
    asyncio.run(manager.library.approve(identifier, "quick"))
    profile = manager.catalog.profiles[manager.library.state.entries[identifier].profile_id]
    assert profile.model.base_url == "http://127.0.0.1:18293"
    runtime.retrieval.close()


def test_router_uses_only_approved_fitting_models_and_requested_roles(tmp_path):
    runtime, manager = controller(tmp_path / "data")
    path = model(tmp_path / "models", "small.gguf")
    model(path.parent, "large.gguf")
    entries = manager.library.scan(str(path.parent))["entries"]
    for entry in entries:
        asyncio.run(
            manager.library.approve(
                entry["id"], "reasoning" if "large" in entry["path"] else "quick"
            )
        )
    manager.library.state.automatic = True
    selected = []

    async def choose(identifier):
        selected.append(identifier)
        return {"selected": identifier, "switched": True}

    manager.library.activate = choose
    asyncio.run(manager.library.route("Please analyze this proof"))
    assert "large" in manager.library.state.entries[selected[-1]].path
    runtime.compute.sampler = lambda: {
        "ram_available_bytes": 32,
        "ram_used_percent": 99,
        "disk_free_bytes": 2048,
    }
    asyncio.run(manager.library.route("hi"))
    assert len(selected) == 1
    assert "No approved alternative" in manager.library.last_route["reason"]
    runtime.retrieval.close()


def test_library_paths_and_configuration_are_owner_local_only(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), ProbeProvider())
    app.state.auth.initialize("synthetic-library-owner-password")
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/models/library").status_code == 401
        client.post("/auth/session", json={"mode": "demo"})
        assert client.get("/models/library").status_code == 403
        assert client.post("/performance", json={"mode": "priority"}).status_code == 403
        client.post("/auth/logout", json={})
        client.post("/auth/login", json={"password": "synthetic-library-owner-password"})
        assert client.get("/models/library").json()["automatic"] is False
        assert client.post("/models/automatic", json={"enabled": True}).status_code == 200
        assert client.post("/performance", json={"mode": "priority"}).json()["mode"] == "priority"
        assert client.post("/performance", json={"mode": "unlimited"}).status_code == 422
        report = client.get("/diagnostics").json()
        assert str(tmp_path) not in str(report)
        assert "synthetic-library-owner-password" not in str(report)


def test_eco_priority_keep_hard_ram_guard_and_explain_missing_telemetry(tmp_path):
    runtime, manager = controller(tmp_path)
    runtime.compute.sampler = lambda: {
        "ram_available_bytes": 1024**3,
        "ram_used_percent": 95,
        "disk_free_bytes": 1024**3,
    }
    assert "RESOURCE.RAM_PRESSURE" in runtime.compute.observe()["reasons"]
    asyncio.run(runtime.compute.set_mode("priority"))
    assert "RESOURCE.RAM_PRESSURE" not in runtime.compute.observe()["reasons"]
    runtime.compute.sampler = lambda: {
        "ram_available_bytes": 64 * 1024**2,
        "ram_used_percent": 50,
        "disk_free_bytes": 1024**3,
    }
    assert "RESOURCE.RAM_PRESSURE" in runtime.compute.observe()["reasons"]
    runtime.compute.sampler = lambda: {}
    assert "RESOURCE.TELEMETRY_UNAVAILABLE" in runtime.compute.observe()["reasons"]
    runtime.retrieval.close()


def test_failed_candidate_restores_previous_model_and_does_not_change_default(tmp_path):
    from adam.models.base import ModelHealth

    runtime, manager = controller(tmp_path / "data")
    path = model(tmp_path / "models")
    identifier = manager.library.scan(str(path.parent))["entries"][0]["id"]
    asyncio.run(manager.library.approve(identifier, "quick"))
    original_model = runtime.compute.settings.model.model_dump()

    class BadCandidate(ProbeProvider):
        async def health_check(self):
            return ModelHealth(status="DEGRADED", model_id="bad", reason="MODEL.UNAVAILABLE")

    manager.factory = lambda profile: (
        ProbeProvider() if profile.profile_id == "current" else BadCandidate()
    )
    with pytest.raises(ComputeError, match="MODEL.UNAVAILABLE"):
        asyncio.run(manager.library.activate(identifier))
    assert manager.active_id == manager.catalog.default_id == "current"
    assert runtime.compute.settings.model.model_dump() == original_model
    assert runtime.compute.state == "LOADED" and runtime.compute.error is None
    assert "model-selection.json" not in [p.name for p in (tmp_path / "data/config").iterdir()]
    runtime.retrieval.close()
