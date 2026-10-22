import json

from adam.api.app import create_app
from adam.core.config import Settings
from adam.desktop.service import desktop_app
from adam.evals.suite import ProbeProvider
from fastapi.testclient import TestClient

NONCE = "synthetic-desktop-pipe-capability-827197412"
PASSWORD = "synthetic-desktop-owner-passphrase-82719"


def client_for(root):
    return TestClient(
        desktop_app(Settings(data_dir=root), NONCE, probe=True),
        base_url="http://localhost",
        headers={"x-adam-desktop": NONCE},
    )


def test_private_capability_and_origin_are_both_required(tmp_path):
    with client_for(tmp_path) as client:
        assert client.get("/desktop/status").status_code == 200
        client.headers.clear()
        assert client.get("/health").status_code == 403
        assert client.post("/desktop/setup", json={"password": PASSWORD}).status_code == 403
        client.headers["x-adam-desktop"] = "wrong-capability"
        assert client.get("/desktop/status").status_code == 403
        client.headers["x-adam-desktop"] = NONCE
        client.headers["origin"] = "https://foreign.example"
        assert client.get("/desktop/status").status_code == 403
        assert client.post("/desktop/setup", json={"password": PASSWORD}).status_code == 403


def test_non_ascii_capability_is_denied_without_server_error(tmp_path):
    with client_for(tmp_path) as client:
        result = client.get("/desktop/status", headers={"x-adam-desktop": b"\xff"})
        assert result.status_code == 403


def test_setup_is_one_time_and_never_an_owner_login(tmp_path):
    with client_for(tmp_path) as client:
        assert client.get("/desktop/status").json()["configured"] is False
        assert (
            client.post("/desktop/setup", json={"password": PASSWORD, "mode": "owner"}).status_code
            == 422
        )
        assert client.post("/desktop/setup", json={"password": "short"}).status_code == 409
        result = client.post("/desktop/setup", json={"password": PASSWORD})
        assert result.json() == {"configured": True} and "token" not in result.text
        assert client.get("/memory").status_code == 401
        assert (
            client.post("/desktop/setup", json={"password": PASSWORD}).json()["error"]
            == "AUTH.ALREADY_CONFIGURED"
        )
        assert client.post("/auth/login", json={"password": PASSWORD}).status_code == 200
        assert client.get("/auth/status").json()["mode"] == "owner"


def test_normal_api_has_no_desktop_setup_authority(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), ProbeProvider())
    with TestClient(app, base_url="http://localhost") as client:
        assert client.post("/desktop/setup", json={"password": PASSWORD}).status_code == 401
        assert not app.state.auth.configured()


def test_stream_history_and_demo_store_remain_separate(tmp_path):
    with client_for(tmp_path) as client:
        client.post("/desktop/setup", json={"password": PASSWORD})
        client.post("/auth/login", json={"password": PASSWORD})
        result = client.post(
            "/desktop/chat", json={"text": "/remember preference editor = SyntheticStudio"}
        )
        assert result.status_code == 200
        events = [json.loads(line) for line in result.text.splitlines()]
        assert events[-1]["event_type"] == "agent.completed"
        session = events[-1]["session_id"]
        assert "SyntheticStudio" in client.get(f"/sessions/{session}/history").text
        client.post("/auth/switch", json={"mode": "demo"})
        assert client.get("/sessions").json() != [{"session_id": session}]
        assert client.get(f"/sessions/{session}/history").json() == []
        assert "SyntheticStudio" not in client.get("/memory?query=editor").text
        assert client.get("/developer/compute").status_code == 403


def test_invalid_stream_and_secret_ingress_do_not_echo_request(tmp_path):
    with client_for(tmp_path) as client:
        client.post("/desktop/setup", json={"password": PASSWORD})
        client.post("/auth/login", json={"password": PASSWORD})
        result = client.post("/desktop/chat", json={"text": "fixture", "admin": True})
        assert result.status_code == 422 and "fixture" not in result.text
        result = client.post(
            "/desktop/chat", json={"text": "my API key is sk-synthetic-secret-827197411"}
        )
        assert "sk-synthetic-secret" not in result.text
        assert "agent.error" in result.text


def test_recovery_has_no_setup_or_store_initialization(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    path.write_bytes(b"synthetic corrupt database")
    before = path.read_bytes()
    with client_for(tmp_path) as client:
        assert client.get("/desktop/status").json()["recovery"] is True
        assert client.post("/desktop/setup", json={"password": PASSWORD}).status_code == 409
    assert path.read_bytes() == before
    assert not (tmp_path / "security/auth.sqlite3").exists()
