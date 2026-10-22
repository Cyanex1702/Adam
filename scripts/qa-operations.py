"""Live source/frozen scheduler API, restart and privacy verification with disposable data."""

import argparse
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from adam import APP_VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    checks = []

    def check(name, condition):
        assert condition, name
        checks.append(name)

    password = "synthetic-operations-qa-passphrase-812947"
    with tempfile.TemporaryDirectory(prefix="adam-operations-qa-") as directory:
        job = None
        for iteration in range(2):
            command = (
                [str(args.service.resolve())]
                if args.service
                else [sys.executable, "-m", "adam.desktop.service"]
            )
            command += ["--probe", "--data-dir", directory]
            child = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                ready = queue.Queue()
                threading.Thread(
                    target=lambda process=child, channel=ready: channel.put(
                        process.stdout.readline()
                    ),
                    daemon=True,
                ).start()
                receipt = json.loads(ready.get(timeout=150))
                headers = {"x-adam-desktop": receipt["nonce"]}
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{receipt['port']}", headers=headers, timeout=30
                ) as client:
                    if iteration == 0:
                        check(
                            "first-launch setup",
                            client.post("/desktop/setup", json={"password": password}).status_code
                            == 200,
                        )
                    login = client.post("/auth/login", json={"password": password}).json()
                    client.headers["Authorization"] = "Bearer " + login["token"]
                    status = client.get("/operations").json()
                    check(
                        "proactive default off " + str(iteration),
                        not status["preferences"]["proactive"],
                    )
                    if iteration == 0:
                        body = {
                            "request_id": str(uuid4()),
                            "text": "Synthetic reminder",
                            "due_at": (datetime.now(UTC) + timedelta(seconds=2)).isoformat(),
                            "every_seconds": 60,
                        }
                        response = client.post("/operations/schedule", json=body)
                        check("create recurring schedule", response.status_code == 200)
                        job = response.json()["id"]
                        duplicate = client.post("/operations/schedule", json=body)
                        check("idempotent schedule retry", duplicate.json()["id"] == job)
                        wrong = client.post(
                            "/operations/schedule", json={**body, "text": "conflicting text"}
                        )
                        check("id conflict denied", wrong.status_code == 409)
                        invalid = client.post(
                            "/operations/schedule",
                            json={
                                **body,
                                "request_id": str(uuid4()),
                                "due_at": "2026-10-10T10:00:00",
                            },
                        )
                        check("ambiguous timestamp denied", invalid.status_code == 422)
                        deadline = time.monotonic() + 15
                        updates = []
                        while time.monotonic() < deadline:
                            updates = client.get("/operations/inbox").json()
                            if updates:
                                break
                            time.sleep(0.2)
                        check(
                            "background worker dispatches reminder",
                            len(updates) == 1 and updates[0]["text"] == "Synthetic reminder",
                        )
                        check(
                            "notification explains cause",
                            "explicitly scheduled" in updates[0]["reason"],
                        )
                        preferences = status["preferences"]
                        client.post(
                            "/operations/preferences", json={**preferences, "enabled": False}
                        )
                        check(
                            "paused delivery suppressed",
                            client.get("/operations/inbox").json() == [],
                        )
                        client.post("/operations/preferences", json=preferences)
                        check(
                            "resume preserves queued update",
                            len(client.get("/operations/inbox").json()) == 1,
                        )
                        guest = client.post("/auth/switch", json={"mode": "guest"}).json()
                        client.headers["Authorization"] = "Bearer " + guest["token"]
                        check(
                            "guest cannot read owner operations",
                            client.get("/operations").status_code == 403,
                        )
                    else:
                        check(
                            "scheduled job survives process restart",
                            any(
                                item["id"] == job and item["state"] == "SCHEDULED"
                                for item in status["jobs"]
                            ),
                        )
                        updates = client.get("/operations/inbox").json()
                        check("notification queue survives restart", len(updates) == 1)
                        check(
                            "acknowledge",
                            client.post(
                                "/operations/acknowledge", json={"identifier": updates[0]["id"]}
                            ).status_code
                            == 200,
                        )
                        check(
                            "ack removes pending update",
                            client.get("/operations/inbox").json() == [],
                        )
                        check(
                            "cancel scheduled job",
                            client.post("/operations/cancel", json={"identifier": job}).status_code
                            == 200,
                        )
                        check(
                            "cancel persists",
                            client.get("/operations").json()["jobs"][0]["state"] == "CANCELLED",
                        )
            finally:
                child.stdin.close()
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                check("owned sidecar shuts down " + str(iteration), child.returncode == 0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "release": APP_VERSION,
        "target": "frozen" if args.service else "source",
        "passed": len(checks),
        "checks": checks,
        "limits": "Disposable stores; no physical Android or OS notification permission test.",
    }
    args.output.write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(f"Operations QA: {len(checks)} checks passed")


if __name__ == "__main__":
    main()
