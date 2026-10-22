import json
import sqlite3
from contextlib import closing

import pytest
from adam.api.app import create_app
from adam.core.config import Settings
from adam.evals.suite import ProbeProvider
from adam.intelligence.service import Goal, Intelligence, Link
from adam.resilience.archive import BackupService
from adam.resilience.recovery import inspect
from adam.resilience.restore import RestoreService
from adam.training.service import Training
from fastapi.testclient import TestClient
from test_backup import OWNER, PASSWORD, seeded
from test_training_portfolio import example


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), ProbeProvider())
    app.state.auth.initialize(OWNER)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client, app


def login(client):
    result = client.post("/auth/login", json={"password": OWNER})
    assert result.status_code == 200
    return result.json()["token"]


def test_owner_intelligence_goals_and_private_traces(client):
    http, app = client
    login(http)
    result = http.post("/personal/goal", json={"title": "Fictional API goal", "project": "Cedar"})
    assert result.status_code == 200
    goal = result.json()
    assert http.get("/personal").json()["goals"][0]["title"] == "Fictional API goal"
    completed = {**goal, "status": "COMPLETED", "progress": 100}
    assert http.post("/personal/goal", json=completed).status_code == 200
    assert http.post("/personal/goal", json=completed).status_code == 409
    assert all(
        "Fictional API goal" not in item.model_dump_json()
        for item in app.state.runtime.traces.list()
    )


def test_training_needs_fresh_elevation_and_remains_optional(client):
    http, _ = client
    login(http)
    assert http.get("/training").status_code == 403
    assert http.post("/auth/elevate", json={"password": OWNER}).status_code == 200
    assert not http.get("/training").json()["enabled"]
    assert http.post("/training/example", json=example().model_dump()).status_code == 409
    assert http.post("/training/configure", json={"enabled": True}).status_code == 200
    assert http.post("/training/example", json=example().model_dump()).status_code == 200
    exported = http.post("/training/dataset", json={})
    assert exported.status_code == 200 and exported.json()["examples"] == 1
    assert http.get("/training/recipe").json()["status"] == "EXPERIMENTAL_NOT_EXECUTED"
    http.post("/auth/logout")
    assert http.post("/training/dataset", json={}).status_code == 401


def test_demo_never_reads_owner_and_can_exercise_synthetic_tools(client):
    http, app = client
    login(http)
    owner = http.post(
        "/chat", json={"text": "/remember project private = OwnerPrivateSentinelCedar93172"}
    ).json()
    owner_id = owner["payload"]["result"]["memory"]["memory_id"]
    demo = http.post("/auth/session", json={"mode": "demo"})
    assert demo.status_code == 200
    state = http.get("/personal")
    assert state.status_code == 200 and state.json()["goals"]
    assert "OwnerPrivateSentinelCedar93172" not in state.text
    graph = http.post("/personal/graph", json={"query": "Cedar"})
    assert graph.json()["links"] and "OwnerPrivateSentinelCedar93172" not in graph.text
    denied = http.post(
        "/personal/link",
        json={"memory_id": owner_id, "subject": "Cedar", "relation": "uses", "object": "Studio"},
    )
    assert denied.status_code == 409
    assert http.get("/training").status_code == 403
    assert (
        http.post(
            "/portfolio/demo-tool", json={"action": "write_note", "text": "Fictional API note"}
        ).json()["status"]
        == "VERIFIED"
    )
    assert (
        http.post("/portfolio/demo-tool", json={"action": "undo_note"}).json()["status"] == "UNDONE"
    )
    assert app.state.runtime.memories.search("OwnerPrivateSentinelCedar93172")


def test_guest_cannot_access_personal_or_training_and_owner_cannot_use_demo_write(client):
    http, _ = client
    login(http)
    assert http.post("/portfolio/demo-tool", json={"action": "write_note"}).status_code == 403
    http.post("/auth/session", json={"mode": "guest"})
    assert http.get("/personal").status_code == 403
    assert http.get("/training").status_code == 403
    assert http.get("/portfolio").status_code == 200
    assert http.post("/portfolio/demo-tool", json={"action": "write_note"}).status_code == 403


def test_new_interfaces_bound_request_bodies(client):
    http, _ = client
    login(http)
    response = http.post(
        "/personal/graph",
        content=json.dumps({"query": "x" * 70000}),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_schema_six_backup_restores_and_migrates_to_seven(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path / "old")
    runtime.retrieval.close()
    with runtime.store.connect() as db:
        for table in [
            "personal_goal_events",
            "personal_goals",
            "personal_links",
            "training_examples",
            "training_settings",
        ]:
            db.execute("DROP TABLE " + table)
        db.execute("DELETE FROM schema_migrations WHERE version=7")
    assert inspect(settings)["mode"] == "HEALTHY"
    service = BackupService(settings)
    receipt = service.create(PASSWORD)
    archive = service.path(receipt.backup_id)
    assert service.read(archive, PASSWORD)[0].schemas["runtime.sqlite3"] == 6
    target = tmp_path / "restored"
    assert RestoreService().restore(archive, PASSWORD, target)["status"] == "VERIFIED"
    with closing(sqlite3.connect(target / "runtime.sqlite3")) as db:
        assert db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 7
        assert "SnapshotStudio" in db.execute("SELECT record FROM memories").fetchone()[0]


def test_personal_structures_and_approved_examples_survive_restore_with_consent_reset(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path / "source")
    personal = Intelligence(runtime.memories)
    personal.save_goal(Goal(title="Synthetic portable goal"))
    source = runtime.memories.search("editor")[0]
    personal.link(
        Link(memory_id=source.memory_id, subject="editor", relation="uses", object="SnapshotStudio")
    )
    training = Training(runtime.store)
    training.configure(True)
    training.add(example())
    service = BackupService(settings)
    receipt = service.create(PASSWORD)
    runtime.retrieval.close()
    target = tmp_path / "restored"
    RestoreService().restore(service.path(receipt.backup_id), PASSWORD, target)
    with closing(sqlite3.connect(target / "runtime.sqlite3")) as db:
        assert db.execute("SELECT count(*) FROM personal_links").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM personal_goals").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM training_examples").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM training_settings").fetchone()[0] == 0
