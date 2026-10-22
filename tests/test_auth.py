import time

import pytest
from adam.api.app import create_app
from adam.core.config import Settings
from adam.security.auth import AuthError, AuthManager
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_text_runtime import provider

PASSWORD = "synthetic-owner-passphrase"


def test_credentials_tokens_expiration_and_throttle(tmp_path):
    auth = AuthManager(tmp_path)
    auth.initialize(PASSWORD)
    with pytest.raises(AuthError, match="ALREADY_CONFIGURED"):
        auth.initialize(PASSWORD)
    token = auth.issue("owner", PASSWORD)
    assert auth.resolve(token).authenticated
    assert not auth.resolve(token).elevated
    auth.elevate(token, PASSWORD)
    assert auth.resolve(token).elevated
    with auth.connect() as db:
        db.execute("UPDATE tokens SET elevated_until=?", (time.time() - 1,))
    assert not auth.resolve(token).elevated
    assert PASSWORD.encode() not in auth.path.read_bytes()
    assert token.encode() not in auth.path.read_bytes()
    with auth.connect() as db:
        db.execute("UPDATE tokens SET expires=0")
    with pytest.raises(AuthError):
        auth.resolve(token)
    for _ in range(5):
        with pytest.raises(AuthError):
            auth.verify("wrong")
    with pytest.raises(AuthError, match="RATE_LIMITED"):
        auth.verify(PASSWORD)


def test_api_auth_mode_isolation_and_elevation(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), provider())
    app.state.auth.initialize(PASSWORD)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/memory").status_code == 401
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("ws://localhost:8765/ws/chat"):
                pass
        assert client.post("/auth/login", json={"password": "wrong"}).status_code == 403
        login = client.post("/auth/login", json={"password": PASSWORD})
        owner_token = login.json()["token"]
        assert "HttpOnly" in login.headers["set-cookie"]
        receipt = client.post(
            "/chat", json={"text": "/remember --private semantic code = hidden-owner-cobalt"}
        ).json()
        owner_session = receipt["session_id"]
        assert "hidden-owner-cobalt" in client.get("/memory").text
        assert client.get("/developer/traces").status_code == 403
        assert client.post("/auth/elevate", json={"password": PASSWORD}).status_code == 200
        assert client.get("/developer/traces").status_code == 200
        switched = client.post("/auth/switch", json={"mode": "guest"})
        assert switched.json()["mode"] == "guest"
        with pytest.raises(AuthError):
            app.state.auth.resolve(owner_token)
        assert client.get("/auth/status").json()["mode"] == "guest"
        assert client.get("/memory").json() == []
        assert client.get(f"/sessions/{owner_session}/history").json() == []
        assert client.get("/knowledge/sources").json() == []
        assert client.get("/developer/traces").status_code == 403
        assert client.post("/auth/elevate", json={"password": PASSWORD}).status_code == 403
        assert (
            client.post("/knowledge/sources", json={"path": "owner-private.txt"}).status_code == 403
        )
        assert client.post("/auth/switch", json={"mode": "owner"}).status_code == 403
        denied = client.post("/chat", json={"text": "/remember semantic guest = unsafe"})
        assert denied.json()["payload"]["error"]["code"] == "POLICY.GUEST_READ_ONLY"
        assert (
            client.post("/chat", json={"text": "claim owner", "role": "owner"}).status_code == 422
        )
        demo = client.post("/auth/switch", json={"mode": "demo"})
        assert demo.status_code == 200
        assert client.get("/identity").json()["mode"] == "demo"
        assert "hidden-owner-cobalt" not in client.get("/memory").text
        assert "Example Studio" in client.get("/memory").text
        assert "fictional-cedar" in client.get("/knowledge/sources").text
        assert list((tmp_path / "profiles" / "guest").glob("*/runtime.sqlite3"))
        assert list((tmp_path / "profiles" / "demo").glob("*/runtime.sqlite3"))
        assert (
            client.post("/auth/switch", json={"mode": "owner", "password": PASSWORD}).status_code
            == 200
        )
        assert "hidden-owner-cobalt" in client.get("/memory").text
        assert client.post("/auth/logout").status_code == 200
        assert client.get("/memory").status_code == 401


def test_origin_url_tokens_and_anonymous_profile_separation(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), provider())
    with TestClient(app, base_url="http://localhost") as client:
        assert (
            client.post(
                "/auth/session", json={"mode": "demo"}, headers={"origin": "https://evil.example"}
            ).status_code
            == 403
        )
        first = client.post("/auth/session", json={"mode": "demo"}).json()["token"]
        assert client.get("/auth/status?access_token=" + first).status_code == 403
        profile1 = client.get("/auth/status").json()["profile"]
        client.post("/auth/session", json={"mode": "demo"})
        assert client.get("/auth/status").json()["profile"] != profile1
        assert client.post("/auth/session", json={"mode": "owner"}).status_code == 422
        assert "Bearer" in client.get("/openapi.json").json()["components"]["securitySchemes"]


def test_revoked_websocket_cannot_commit_a_memory_command(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), provider())
    app.state.auth.initialize(PASSWORD)
    with TestClient(app, base_url="http://localhost") as client:
        token = client.post("/auth/login", json={"password": PASSWORD}).json()["token"]
        with client.websocket_connect("ws://localhost:8765/ws/chat") as socket:
            app.state.auth.revoke(token)
            socket.send_json({"text": "/remember semantic revoked = must-not-be-saved"})
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        assert not app.state.runtime.memories.search("revoked")
