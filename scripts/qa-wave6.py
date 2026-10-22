"""Real Qwen/E5 and loopback API QA in synthetic stores; requires local model on 8080."""

import asyncio
import json
import socket
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from adam.api.app import create_app
from adam.core.config import load_settings
from adam.evals.grounded import evaluate as grounded_evaluate
from adam.evals.rag import evaluate as rag_evaluate
from adam.evals.suite import evaluate

PROJECT = Path(__file__).resolve().parent.parent


def main():
    api = None
    thread = None
    # Use the already installed/configured local model; never download assets in QA.
    health = httpx.get("http://127.0.0.1:8080/health", timeout=5)
    if health.json().get("status") != "ok":
        raise RuntimeError("Start the configured local model before real-model QA")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    try:
        with TemporaryDirectory(prefix="adam-wave6-live-") as temporary, ExitStack() as cleanup:
            folder = Path(temporary)
            settings = load_settings(PROJECT / "adam.compact.toml").model_copy(
                update={"data_dir": folder}
            )
            settings.knowledge.allowed_roots = [folder]
            app = create_app(settings)
            app.state.auth.initialize("synthetic-wave6-console-passphrase")
            api = uvicorn.Server(
                uvicorn.Config(
                    app, host="127.0.0.1", port=port, access_log=False, log_level="error"
                )
            )
            thread = threading.Thread(target=api.run)
            thread.start()

            def shutdown():
                api.should_exit = True
                thread.join(timeout=20)

            cleanup.callback(shutdown)
            for _ in range(60):
                try:
                    if (
                        httpx.get(f"http://127.0.0.1:{port}/console", timeout=0.5).status_code
                        == 200
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("QA API startup timed out")
            print("Isolated QA API ready", flush=True)
            checks = []

            def check(name, condition):
                if not condition:
                    raise AssertionError(name)
                checks.append(name)

            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
                check("public static console", client.get("/console").status_code == 200)
                check(
                    "developer denied anonymously",
                    client.get("/developer/health").status_code == 401,
                )
                check(
                    "owner login",
                    client.post(
                        "/auth/login", json={"password": "synthetic-wave6-console-passphrase"}
                    ).status_code
                    == 200,
                )
                check(
                    "unelevated traces denied", client.get("/developer/traces").status_code == 403
                )
                client.post(
                    "/auth/elevate", json={"password": "synthetic-wave6-console-passphrase"}
                )
                check(
                    "live measured process RAM",
                    client.get("/developer/health").json()["resources"]["process_ram_bytes"] > 0,
                )
                check(
                    "VRAM explicitly unavailable",
                    client.get("/developer/health").json()["resources"]["vram_bytes"] is None,
                )
                case = client.post("/developer/evals/replay/task_verify").json()
                check("isolated replay verified", case["passed"])
                check("owner tasks unaffected by replay", client.get("/tasks").json() == [])
                action = client.post(
                    "/tools/preview",
                    json={
                        "name": "notes.create",
                        "arguments": {"path": "live.txt", "text": "Synthetic local evidence"},
                    },
                ).json()
                client.post(
                    f"/actions/{action['action_id']}/approve", json={"digest": action["digest"]}
                )
                check(
                    "live file action",
                    client.post(f"/actions/{action['action_id']}/execute").json()["result"][
                        "status"
                    ]
                    == "VERIFIED",
                )
                trace = client.get(f"/developer/traces/{action['trace_id']}").json()
                check(
                    "tool permission timeline",
                    [item["status"] for item in trace["events"]]
                    == ["PREVIEW", "APPROVED", "RUNNING", "VERIFIED"],
                )
                check("no file text traced", "Synthetic local evidence" not in json.dumps(trace))
                failure = client.post("/tools/preview", json={"name": "shell.exec"}).json()
                check(
                    "failure classified",
                    client.get(f"/developer/traces/{failure['trace_id']}").json()[
                        "error_subsystems"
                    ]
                    == ["tools"],
                )
                check(
                    "security replay",
                    client.post("/developer/evals/replay/encoded_exfiltration").json()["passed"],
                )
                event = client.post(
                    "/chat", json={"text": "/remember preference editor = SyntheticStudio"}
                ).json()
                check(
                    "memory timeline",
                    any(
                        item["subsystem"] == "memory"
                        for item in client.get(f"/developer/traces/{event['trace_id']}").json()[
                            "events"
                        ]
                    ),
                )
                source = folder / "qa-cedar.md"
                source.write_text(
                    "Fictional Cedar launch command: cedar serve --port 9123.\n", encoding="utf-8"
                )
                client.post("/knowledge/sources", json={"path": str(source)})
                event = client.post(
                    "/chat", json={"text": "/ask What is Cedar launch command?"}
                ).json()
                check(
                    "real RAG timeline",
                    any(
                        item["subsystem"] == "knowledge"
                        for item in client.get(f"/developer/traces/{event['trace_id']}").json()[
                            "events"
                        ]
                    ),
                )
                check("memory inspector", bool(client.get("/developer/memory?query=editor").json()))
                check(
                    "RAG inspector",
                    bool(
                        client.get("/developer/knowledge?query=Cedar%20command").json()["evidence"]
                    ),
                )
                client.post("/auth/switch", json={"mode": "guest"})
                check(
                    "guest developer boundary", client.get("/developer/health").status_code == 403
                )
            print("LIVE_HTTP_QA_PASS: " + str(len(checks)), flush=True)
            evidence = PROJECT / "docs/operations/evidence"
            evidence.mkdir(exist_ok=True)
            (evidence / "wave6-live-qa.json").write_text(
                json.dumps(
                    {"passed": True, "checks": len(checks), "passed_checks": checks}, indent=2
                ),
                encoding="utf-8",
            )
            actual = asyncio.run(evaluate(settings, real_model=True, real_rag=True))
            (evidence / "wave6-real-model-eval.json").write_text(
                actual.model_dump_json(indent=2), encoding="utf-8"
            )
            print(
                "REAL_MODEL_EVAL: "
                + str(actual.passed)
                + " "
                + str([(case.name, case.passed) for case in actual.cases]),
                flush=True,
            )
            (folder / "grounded-benchmark").mkdir()
            grounded = grounded_evaluate(folder / "grounded-benchmark")
            (evidence / "wave6-grounding-eval.json").write_text(
                json.dumps(grounded, indent=2), encoding="utf-8"
            )
            print("REAL_GROUNDING_EVAL: " + str(grounded["passed"]), flush=True)
            (folder / "retrieval-benchmark").mkdir()
            rag = rag_evaluate(folder / "retrieval-benchmark")
            (evidence / "wave6-retrieval-eval.json").write_text(
                json.dumps(rag, indent=2), encoding="utf-8"
            )
            print("REAL_RETRIEVAL_EVAL: " + str(rag["passed"]), flush=True)
            check(
                "real evaluation release gate",
                actual.passed and grounded["passed"] and rag["passed"],
            )
            api.should_exit = True
            thread.join(timeout=20)
    finally:
        if api:
            api.should_exit = True
        if thread:
            thread.join(timeout=20)


if __name__ == "__main__":
    main()
