"""Exercise the actual frozen desktop service in a disposable store."""

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
import psutil
from adam import APP_VERSION


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    checks: list[str] = []
    password = "synthetic-desktop-qa-passphrase-918274"

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix="adam-desktop-qa-") as directory:
        session = ""
        for iteration in range(2):
            command = [str(args.service.resolve()), "--data-dir", directory]
            if not args.real:
                command.append("--probe")
            if args.config:
                command.extend(["--config", str(args.config.resolve())])
            child = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                assert child.stdout is not None
                receipt_queue: queue.Queue[str] = queue.Queue()
                threading.Thread(
                    target=lambda process=child, channel=receipt_queue: channel.put(
                        process.stdout.readline()
                    ),
                    daemon=True,
                ).start()
                line = receipt_queue.get(timeout=150)
                if not line:
                    assert child.stderr is not None
                    raise RuntimeError(child.stderr.read()[-3000:])
                receipt = json.loads(line)
                check("ready handshake " + str(iteration), receipt["event"] == "ready")
                origin = f"http://127.0.0.1:{receipt['port']}"
                with httpx.Client(base_url=origin, timeout=180) as client:
                    check(
                        "nonce required " + str(iteration), client.get("/health").status_code == 403
                    )
                    client.headers["x-adam-desktop"] = receipt["nonce"]
                    report = client.get("/desktop/diagnostics")
                    check(
                        "diagnostics available before login " + str(iteration),
                        report.status_code == 200,
                    )
                    check(
                        "diagnostic paths excluded " + str(iteration), directory not in report.text
                    )
                    check(
                        "browser origin denied " + str(iteration),
                        client.get(
                            "/desktop/status", headers={"origin": "http://foreign.example"}
                        ).status_code
                        == 403,
                    )
                    check(
                        "configuration persistence " + str(iteration),
                        client.get("/desktop/status").json()["configured"] == bool(iteration),
                    )
                    if not iteration:
                        check(
                            "first setup",
                            client.post("/desktop/setup", json={"password": password}).status_code
                            == 200,
                        )
                        check("setup not login", client.get("/sessions").status_code == 401)
                    check(
                        "setup one time " + str(iteration),
                        client.post("/desktop/setup", json={"password": password}).status_code
                        == 409,
                    )
                    check(
                        "wrong password denied " + str(iteration),
                        client.post(
                            "/auth/login", json={"password": "synthetic-wrong-password"}
                        ).status_code
                        == 403,
                    )
                    check(
                        "owner login " + str(iteration),
                        client.post("/auth/login", json={"password": password}).status_code == 200,
                    )
                    check(
                        "developer elevation required " + str(iteration),
                        client.get("/developer/compute").status_code == 403,
                    )
                    if args.real and not iteration:
                        deadline = time.monotonic() + 120
                        while (
                            client.get("/desktop/status").json()["model_status"] != "HEALTHY"
                            and time.monotonic() < deadline
                        ):
                            time.sleep(0.25)
                        check(
                            "model becomes ready independently of login",
                            client.get("/desktop/status").json()["model_status"] == "HEALTHY",
                        )
                        process = client.get("/desktop/diagnostics").json()["model"]["process"]
                        owned = psutil.Process(process["pid"])
                        command_line = owned.cmdline()
                        check(
                            "real Eco process priority",
                            owned.nice() == psutil.BELOW_NORMAL_PRIORITY_CLASS,
                        )
                        check(
                            "real Eco inference threads",
                            command_line[command_line.index("-t") + 1]
                            == str(min(2, max(1, (os.cpu_count() or 2) - 1))),
                        )
                        changed = client.post("/performance", json={"mode": "priority"})
                        check(
                            "owner applies Priority without service restart",
                            changed.status_code == 200,
                        )
                        process = client.get("/desktop/diagnostics").json()["model"]["process"]
                        priority = psutil.Process(process["pid"])
                        command_line = priority.cmdline()
                        check(
                            "real Priority process priority",
                            priority.nice() == psutil.ABOVE_NORMAL_PRIORITY_CLASS,
                        )
                        check(
                            "real Priority inference threads",
                            command_line[command_line.index("-t") + 1]
                            == str(min(6, max(1, (os.cpu_count() or 2) - 1))),
                        )
                        check("mode change reaps prior owned process", not owned.is_running())
                        card = client.get("/identity").json()["model"]
                        check("real model identity", card["provider"] != "fixture")
                        answer = client.post("/desktop/chat", json={"text": "What are you?"})
                        actual = [json.loads(item) for item in answer.text.splitlines()]
                        if actual[-1]["event_type"] != "agent.completed":
                            print(
                                "Real transport failure:",
                                actual[-1]
                                .get("payload", {})
                                .get("error", {})
                                .get("code", "missing terminal event"),
                            )
                            print(
                                "Model status:", client.get("/desktop/status").json()["model_error"]
                            )
                        check(
                            "real streamed completion",
                            actual[-1]["event_type"] == "agent.completed",
                        )
                        check(
                            "real token events",
                            any(item["event_type"] == "agent.token" for item in actual),
                        )
                        check("real answer present", len(actual[-1]["payload"]["text"]) > 10)
                    if not iteration:
                        response = client.post(
                            "/desktop/chat",
                            json={"text": "/remember preference editor = FrozenSyntheticStudio"},
                        )
                        events = [json.loads(item) for item in response.text.splitlines()]
                        check(
                            "stream terminal event", events[-1]["event_type"] == "agent.completed"
                        )
                        session = events[-1]["session_id"]
                        check("stream no cache", response.headers["cache-control"] == "no-store")
                        check(
                            "input validation redacts",
                            "private fixture"
                            not in client.post(
                                "/desktop/chat",
                                json={"text": "private fixture", "unexpected": True},
                            ).text,
                        )
                    check(
                        "history persistence " + str(iteration),
                        "FrozenSyntheticStudio" in client.get(f"/sessions/{session}/history").text,
                    )
                    check(
                        "memory persistence " + str(iteration),
                        "FrozenSyntheticStudio" in client.get("/memory?query=editor").text,
                    )
                    check(
                        "switch demo " + str(iteration),
                        client.post("/auth/switch", json={"mode": "demo"}).status_code == 200,
                    )
                    check(
                        "demo history isolated " + str(iteration),
                        client.get(f"/sessions/{session}/history").json() == [],
                    )
                    check(
                        "demo memory isolated " + str(iteration),
                        "FrozenSyntheticStudio" not in client.get("/memory?query=editor").text,
                    )
                    check(
                        "demo developer denied " + str(iteration),
                        client.get("/developer/compute").status_code == 403,
                    )
                    check(
                        "logout " + str(iteration), client.post("/auth/logout").status_code == 200
                    )
                    check(
                        "logout revokes " + str(iteration),
                        client.get("/sessions").status_code == 401,
                    )
            finally:
                if child.stdin:
                    child.stdin.close()
                try:
                    child.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                    raise AssertionError("EOF graceful shutdown timed out") from None
            check("owned EOF shutdown " + str(iteration), child.returncode == 0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "release": APP_VERSION,
                "kind": "frozen-service-real-model"
                if args.real
                else "frozen-service-synthetic-transport",
                "passed": len(checks),
                "checks": checks,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Frozen desktop service: {len(checks)} checks passed")


if __name__ == "__main__":
    main()
