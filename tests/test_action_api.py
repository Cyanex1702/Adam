from adam.api.app import create_app
from adam.core.config import Settings
from fastapi.testclient import TestClient
from test_text_runtime import provider


def test_action_task_api_and_profile_isolation(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), provider())
    password = "synthetic-action-passphrase"
    app.state.auth.initialize(password)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/tools").status_code == 401
        client.post("/auth/login", json={"password": password})
        root = app.state.runtime.actions.scope.root
        action = client.post(
            "/tools/preview",
            json={
                "name": "notes.create",
                "arguments": {"path": "api.txt", "text": "api synthetic note"},
            },
        ).json()
        identifier = action["action_id"]
        assert not (root / "api.txt").exists()
        assert client.post(f"/actions/{identifier}/execute").status_code == 409
        assert (
            client.post(
                f"/actions/{identifier}/approve", json={"digest": action["digest"]}
            ).status_code
            == 409
        )
        client.post("/auth/elevate", json={"password": password})
        assert (
            client.post(
                f"/actions/{identifier}/approve", json={"digest": action["digest"]}
            ).status_code
            == 200
        )
        assert (
            client.post(f"/actions/{identifier}/execute").json()["result"]["status"] == "VERIFIED"
        )
        assert (root / "api.txt").read_text() == "api synthetic note"
        task = client.post("/tasks/plan", json={"goal": "organize ."}).json()
        task_id = task["task_id"]
        assert (
            client.post(f"/tasks/{task_id}/approve", json={"digest": task["digest"]}).status_code
            == 200
        )
        assert client.post(f"/tasks/{task_id}/run").json()["status"] == "COMPLETED"
        assert (root / "txt" / "api.txt").exists()
        undo = client.post(f"/actions/{identifier}/undo-preview")
        assert undo.status_code == 409  # The original path has moved; no guessed undo.
        assert (
            client.post("/tools/preview", json={"name": "shell.exec", "arguments": {}}).status_code
            == 409
        )
        client.post("/auth/switch", json={"mode": "guest"})
        assert client.get("/actions").json() == []
        assert client.get("/tasks").json() == []
        assert client.get(f"/actions/{identifier}").status_code == 409
        assert (
            client.post(
                "/tools/preview",
                json={
                    "name": "notes.create",
                    "arguments": {"path": "guest.txt", "text": "blocked"},
                },
            ).status_code
            == 409
        )
        assert client.post("/tasks/plan", json={"goal": "organize ."}).status_code == 409
        observed = client.post("/tools/preview", json={"name": "files.search"}).json()
        assert client.post(f"/actions/{observed['action_id']}/execute").json()["result"][
            "data"
        ] == {"paths": []}
