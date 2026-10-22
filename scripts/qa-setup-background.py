"""Check queued model setup and cancellation in an isolated frozen profile."""

import argparse
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import httpx
from adam import APP_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks = []

    def check(name, value):
        assert value, name
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix="adam-setup-background-qa-") as temporary:
        child = subprocess.Popen(
            [str(args.service.resolve()), "--probe", "--data-dir", temporary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=dict(
                os.environ,
                ADAM_MODEL_ID="setup-background-offline-qa",
                ADAM_MODEL_URL="http://127.0.0.1:65534",
            ),
        )
        try:
            ready = queue.Queue()
            threading.Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True).start()
            hello = json.loads(ready.get(timeout=150))
            with httpx.Client(
                base_url=f"http://127.0.0.1:{hello['port']}",
                headers={"x-adam-desktop": hello["nonce"]},
                timeout=20,
            ) as client:
                password = "synthetic-setup-owner-932741"
                client.post("/desktop/setup", json={"password": password}).raise_for_status()
                token = client.post("/auth/login", json={"password": password}).json()["token"]
                client.headers["Authorization"] = "Bearer " + token
                check(
                    "setup needs reauthentication",
                    client.post(
                        "/distribution/model", json={"model_id": "qwen3-4b-instruct"}
                    ).status_code
                    == 403,
                )
                client.post("/auth/elevate", json={"password": password}).raise_for_status()
                started = time.monotonic()
                response = client.post(
                    "/distribution/model", json={"model_id": "qwen3-4b-instruct"}
                )
                check(
                    "setup queues without waiting for a large download",
                    response.status_code == 200
                    and response.json()["status"] == "QUEUED"
                    and time.monotonic() - started < 5,
                )
                check(
                    "explicit setup cancellation accepted",
                    client.post("/distribution/cancel", json={}).status_code == 200,
                )
                deadline = time.monotonic() + 45
                progress = {}
                while time.monotonic() < deadline:
                    progress = client.get("/distribution/setup").json()["progress"]
                    if progress["status"] in {
                        "FAILED_OR_CANCELLED",
                        "FAILED",
                        "VERIFIED_RESTART_REQUIRED",
                    }:
                        break
                    time.sleep(0.2)
                check(
                    "cancel or resource guard bounds background work",
                    progress["status"] in {"FAILED_OR_CANCELLED", "FAILED"},
                )
                check(
                    "no profile activation on cancelled setup",
                    not (Path(temporary) / "config/model-catalog.json").exists(),
                )
                check("cancelled setup retains local API", client.get("/health").status_code == 200)
        finally:
            if child.poll() is None:
                child.stdin.write("stop\n")
                child.stdin.flush()
                try:
                    child.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
        check("owned setup service stopped", child.returncode == 0)
    args.output.write_text(
        json.dumps(
            {
                "release": APP_VERSION,
                "passed": True,
                "checks": checks,
                "limits": (
                    "Synthetic owner profile and immediate cancellation; "
                    "no completed model download or quality claim."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"passed": True, "checks": len(checks)}))


if __name__ == "__main__":
    main()
