"""Real loopback API and terminal QA using isolated synthetic data. No model required."""

import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

import httpx
from adam import APP_VERSION
from adam.security.auth import AuthManager


def main() -> None:
    results: list[str] = []

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        results.append(name)

    with tempfile.TemporaryDirectory(prefix="adam-wave5-qa-") as temporary:
        root = Path(temporary)
        password = secrets.token_hex(24)
        AuthManager(root).initialize(password)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        environment = {key: value for key, value in os.environ.items() if key != "ADAM_CONFIG"}
        environment["ADAM_DATA_DIR"] = str(root)
        environment["ADAM_TEXT_ENABLED"] = "false"

        def start() -> subprocess.Popen[bytes]:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "adam.api.app:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--no-access-log",
                ],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(60):
                try:
                    if (
                        httpx.get(f"http://127.0.0.1:{port}/openapi.json", timeout=0.5).status_code
                        == 200
                    ):
                        return process
                except httpx.HTTPError:
                    pass
                if process.poll() is not None:
                    raise RuntimeError("QA API startup failed")
                time.sleep(0.2)
            process.terminate()
            process.wait(timeout=10)
            raise RuntimeError("QA API startup timed out")

        process = start()
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15) as client:
                check("anonymous tools denied", client.get("/tools").status_code == 401)
                check(
                    "owner login",
                    client.post("/auth/login", json={"password": password}).status_code == 200,
                )
                check("registry available", len(client.get("/tools").json()["tools"]) == 12)
                sandbox = root / "tool-sandbox"
                action = client.post(
                    "/tools/preview",
                    json={
                        "name": "notes.create",
                        "arguments": {"path": "synthetic.txt", "text": "local verification text"},
                    },
                ).json()
                identifier = action["action_id"]
                check("dry run leaves files unchanged", not (sandbox / "synthetic.txt").exists())
                check(
                    "unelevated approval denied",
                    client.post(
                        f"/actions/{identifier}/approve", json={"digest": action["digest"]}
                    ).status_code
                    == 409,
                )
                check(
                    "fresh elevation",
                    client.post("/auth/elevate", json={"password": password}).status_code == 200,
                )
                check(
                    "digest mismatch denied",
                    client.post(
                        f"/actions/{identifier}/approve", json={"digest": "incorrect"}
                    ).status_code
                    == 409,
                )
                check(
                    "owner approval",
                    client.post(
                        f"/actions/{identifier}/approve", json={"digest": action["digest"]}
                    ).status_code
                    == 200,
                )
                check(
                    "note effect verified",
                    client.post(f"/actions/{identifier}/execute").json()["result"]["status"]
                    == "VERIFIED",
                )
                check(
                    "actual file bytes",
                    (sandbox / "synthetic.txt").read_text() == "local verification text",
                )
                check(
                    "repeated action idempotent",
                    client.post(f"/actions/{identifier}/execute").json()["result"]["status"]
                    == "VERIFIED",
                )
                check(
                    "outside scope denied",
                    client.post(
                        "/tools/preview",
                        json={
                            "name": "notes.create",
                            "arguments": {"path": "../outside.txt", "text": "blocked"},
                        },
                    ).status_code
                    == 409,
                )
                check(
                    "arbitrary shell denied",
                    client.post("/tools/preview", json={"name": "shell.exec"}).status_code == 409,
                )
                check(
                    "ambiguous goal clarified",
                    client.post("/tasks/plan", json={"goal": "clean everything"}).json()["error"]
                    == "TASK.CLARIFICATION_REQUIRED",
                )
                task = client.post("/tasks/plan", json={"goal": "organize ."}).json()
                task_id = task["task_id"]
                check(
                    "organize is preview only",
                    (sandbox / "synthetic.txt").exists() and not (sandbox / "txt").exists(),
                )
                check(
                    "task approved",
                    client.post(
                        f"/tasks/{task_id}/approve", json={"digest": task["digest"]}
                    ).status_code
                    == 200,
                )
                check(
                    "task completed",
                    client.post(f"/tasks/{task_id}/run").json()["status"] == "COMPLETED",
                )
                check(
                    "organized bytes verified",
                    (sandbox / "txt" / "synthetic.txt").read_text() == "local verification text",
                )
                count = len(client.get("/actions").json())
                move = next(
                    item
                    for item in client.get("/actions").json()
                    if item["call"]["name"] == "files.move"
                )
                inverse = client.post(f"/actions/{move['action_id']}/undo-preview").json()
                check("undo remains a preview", (sandbox / "txt" / "synthetic.txt").exists())
                client.post(
                    f"/actions/{inverse['action_id']}/approve", json={"digest": inverse["digest"]}
                )
                check(
                    "undo verified",
                    client.post(f"/actions/{inverse['action_id']}/execute").json()["result"][
                        "status"
                    ]
                    == "VERIFIED",
                )
                check(
                    "undo actual bytes",
                    (sandbox / "synthetic.txt").read_text() == "local verification text",
                )
                check("snapshots retained", bool(list((sandbox / ".adam-snapshots").rglob("file"))))
                denied = client.post(
                    "/tools/preview",
                    json={
                        "name": "notes.create",
                        "arguments": {"path": "denied.txt", "text": "denied"},
                    },
                ).json()
                client.post(
                    f"/actions/{denied['action_id']}/approve",
                    json={"digest": denied["digest"], "allow": False},
                )
                check(
                    "denied effect blocked",
                    client.post(f"/actions/{denied['action_id']}/execute").status_code == 409
                    and not (sandbox / "denied.txt").exists(),
                )
                client.post("/auth/switch", json={"mode": "guest"})
                check("guest cannot see owner actions", client.get("/actions").json() == [])
                check("guest cannot see owner tasks", client.get("/tasks").json() == [])
                check(
                    "guest write denied",
                    client.post(
                        "/tools/preview",
                        json={
                            "name": "notes.create",
                            "arguments": {"path": "guest.txt", "text": "blocked"},
                        },
                    ).status_code
                    == 409,
                )
                process.terminate()
                process.wait(timeout=10)
                process = start()
                client.cookies.clear()
                client.post("/auth/login", json={"password": password})
                client.post("/auth/elevate", json={"password": password})
                check(
                    "task restart completed receipt",
                    client.post(f"/tasks/{task_id}/run").json()["status"] == "COMPLETED",
                )
                check(
                    "restart does not repeat effects",
                    (sandbox / "synthetic.txt").exists()
                    and not (sandbox / "txt" / "synthetic.txt").exists(),
                )
                check(
                    "journal persists across restart",
                    len(client.get("/actions").json()) == count + 2,
                )
        finally:
            process.terminate()
            process.wait(timeout=10)
        environment["ADAM_DATA_DIR"] = str(root / "terminal")
        terminal = subprocess.run(
            [sys.executable, "-m", "adam.cli", "chat"],
            env=environment,
            input='/tool {"name":"system.info"}\n/plan diagnose .\n/quit\n',
            text=True,
            capture_output=True,
            timeout=30,
        )
        check(
            "real terminal explicit tool",
            terminal.returncode == 0 and '"status": "VERIFIED"' in terminal.stdout,
        )
        check("real terminal task preview", '"status": "WAITING_FOR_PERMISSION"' in terminal.stdout)
        for name in ["actions", "tasks"]:
            with closing(sqlite3.connect(root / f"{name}.sqlite3")) as db, db:
                check(
                    f"{name} schema version", db.execute("PRAGMA user_version").fetchone()[0] == 1
                )
    report = {
        "version": APP_VERSION,
        "status": "PASS",
        "checks": len(results),
        "passed": results,
        "model_required": False,
        "filesystem": "isolated synthetic local PC sandbox",
    }
    target = Path(__file__).resolve().parents[1] / "docs/operations/evidence/wave5-live-qa.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "checks": len(results)}))


if __name__ == "__main__":
    main()
