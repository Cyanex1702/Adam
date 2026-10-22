from pathlib import Path

from adam.api.app import create_app
from adam.core.config import Settings
from auth_client import OwnerClient as TestClient
from test_text_runtime import provider


def test_memory_api_and_forget_after_restart(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    with TestClient(
        create_app(settings, provider("offline")), base_url="http://localhost"
    ) as client:
        response = client.post(
            "/chat", json={"text": "/remember --private project framework = ADAM"}
        )
        assert response.status_code == 200
        result = response.json()
        sid = result["session_id"]
        mid = result["payload"]["result"]["memory"]["memory_id"]
        assert client.get("/memory?query=framework").json()[0]["allowed_audiences"] == ["owner"]
        assert client.get(f"/sessions/{sid}/history").json()[0]["trace_id"] == result["trace_id"]
        assert (
            client.put(
                f"/sessions/{sid}/working", json={"instructions": ["api_key=raw-secret"]}
            ).status_code
            == 400
        )
    with TestClient(
        create_app(settings, provider("offline")), base_url="http://localhost"
    ) as client:
        assert client.get("/identity").json()["capabilities"]["persistent_memory"] == "AVAILABLE"
        assert client.delete(f"/memory/{mid}").status_code == 200
        assert client.get("/memory?query=framework&historical=true&archived=true").json() == []
