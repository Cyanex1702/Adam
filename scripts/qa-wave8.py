"""Real GPU model lifecycle and gated swaps in a disposable owner store.

Requires the two already installed Qwen GGUFs and E5. No downloads or personal
store access. Uses actual telemetry, a 512 MiB RAM floor and a 98% usage ceiling
for this temporary QA profile. Default application policy remains unchanged.
"""

import json
import socket
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from adam import APP_VERSION
from adam.api.app import create_app
from adam.compute.catalog import Catalog, ModelProfile, publish
from adam.compute.hardware import profile
from adam.compute.migration import continuity
from adam.core.config import load_settings

PROJECT = Path(__file__).resolve().parents[1]
PASSWORD = "synthetic-wave8-owner-passphrase-819274"


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main():
    passed = []
    benchmarks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        passed.append(name)
        print(json.dumps({"check": name, "status": "PASS"}), flush=True)

    with TemporaryDirectory(prefix="adam-wave8-live-") as temporary:
        root = Path(temporary)
        settings = load_settings(PROJECT / "adam.compact.toml", env={})
        settings.data_dir = root
        settings.model.base_url = f"http://127.0.0.1:{free_port()}"
        settings.model.temperature = 0.1
        settings.model.max_tokens = 768
        settings.compute.ram_pressure_percent = 98
        settings.knowledge.allowed_roots = [root]
        baseline = ModelProfile(
            profile_id="current",
            model=settings.model,
            managed=True,
            model_file="qwen3-4b-instruct.gguf",
            device="vulkan",
        )
        candidate_config = settings.model.model_copy(
            update={
                "base_url": f"http://127.0.0.1:{free_port()}",
                "model_id": "qwen3-4b-abliterated",
                "display_name": "Qwen3-4B abliteration candidate",
                "context_limit": 2048,
            }
        )
        candidate = ModelProfile(
            profile_id="candidate",
            model=candidate_config,
            managed=True,
            model_file="qwen3-4b-abliterated.gguf",
            device="vulkan",
        )
        publish(root, "config/model-catalog.json", Catalog(profiles={"current": baseline}))
        app = create_app(settings)
        app.state.auth.initialize(PASSWORD)
        server = uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=free_port(), access_log=False, log_level="error"
            )
        )
        thread = threading.Thread(target=server.run)
        thread.start()
        try:
            for _ in range(180):
                if server.started:
                    break
                if not thread.is_alive():
                    raise RuntimeError("QA API startup failed")
                time.sleep(0.5)
            else:
                raise RuntimeError("QA API startup timed out")
            with httpx.Client(
                base_url=f"http://127.0.0.1:{server.config.port}", timeout=600
            ) as client:

                def elevate():
                    check(
                        "fresh owner reauthentication",
                        client.post("/auth/login", json={"password": PASSWORD}).status_code == 200
                        and client.post("/auth/elevate", json={"password": PASSWORD}).status_code
                        == 200,
                    )

                check(
                    "anonymous compute denied", client.get("/developer/compute").status_code == 401
                )
                elevate()
                status = client.get("/developer/compute").json()
                check("owned baseline loaded", status["lifecycle"] == "LOADED")
                check("actual GPU telemetry available", bool(status["resources"]["gpus"]))
                check(
                    "configured capability reduction reported",
                    status["capabilities"]["deep_reasoning"] == "REDUCED",
                )
                check(
                    "synthetic memory saved",
                    client.post(
                        "/chat", json={"text": "/remember preference editor = SyntheticStudio"}
                    ).status_code
                    == 200,
                )
                check(
                    "candidate registered",
                    client.post(
                        "/developer/models", json=candidate.model_dump(mode="json")
                    ).status_code
                    == 200,
                )
                before = continuity(settings)
                for identifier in ["current", "candidate"]:
                    elevate()
                    result = client.post(f"/developer/models/{identifier}/benchmark", json={})
                    check(f"{identifier} benchmark receipt", result.status_code == 200)
                    report = result.json()
                    benchmarks.append(report)
                    destination = (
                        PROJECT / "docs/operations/evidence" / f"wave8-{identifier}-benchmark.json"
                    )
                    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                    print(
                        json.dumps(
                            {
                                "failed_cases": [
                                    case
                                    for suite in ("local", "security")
                                    for case in report[suite]["cases"]
                                    if not case["passed"]
                                ]
                            }
                        ),
                        flush=True,
                    )
                    check(f"{identifier} complete gates", report["eligible"])
                    check(
                        f"{identifier} identity and memory intact", continuity(settings) == before
                    )
                    check(
                        f"{identifier} throughput measured",
                        report["metrics"]["token_count"] > 0
                        and report["metrics"]["tokens_per_second_after_first"] > 0,
                    )
                evidence = benchmarks[-1]["benchmark_id"]
                elevate()
                refused = client.post(
                    "/developer/models/candidate/promote", json={"benchmark_id": evidence}
                )
                check(
                    "smaller context requires explicit acceptance",
                    refused.status_code == 409
                    and refused.json()["error"] == "MODEL.REDUCED_CAPABILITY_ACK_REQUIRED",
                )
                trial = client.post(
                    "/developer/models/candidate/promote",
                    json={"benchmark_id": evidence, "acknowledge_reduced": True},
                )
                check(
                    "candidate trial loads owned model",
                    trial.status_code == 200 and trial.json()["status"] == "TRIAL",
                )
                check(
                    "trial keeps old default",
                    client.get("/developer/models").json()["default"] == "current",
                )
                check("trial preserves identity and memory bytes", continuity(settings) == before)
                check(
                    "trial reports smaller context",
                    client.get("/identity").json()["model"]["context_limit"] == 2048,
                )
                reply = client.post(
                    "/chat", json={"text": "Which editor do I prefer? Answer briefly."}
                )
                check(
                    "candidate recalls retained memory",
                    reply.status_code == 200 and "SyntheticStudio" in reply.text,
                )
                before_rollback = continuity(settings)
                check(
                    "trial rolls back",
                    client.post("/developer/models/rollback", json={}).json()["status"]
                    == "ROLLED_BACK",
                )
                check("rollback preserves memory", continuity(settings) == before_rollback)
                check(
                    "baseline becomes active again",
                    client.get("/identity").json()["model"]["model_id"] == baseline.model.model_id,
                )
                elevate()
                check(
                    "second trial succeeds",
                    client.post(
                        "/developer/models/candidate/promote",
                        json={"benchmark_id": evidence, "acknowledge_reduced": True},
                    ).status_code
                    == 200,
                )
                check(
                    "finalize commits selection",
                    client.post("/developer/models/finalize", json={}).json()["status"]
                    == "FINALIZED",
                )
                check(
                    "persisted settings select candidate",
                    load_settings(env={"ADAM_DATA_DIR": str(root)}).model.model_id
                    == candidate.model.model_id,
                )
                check(
                    "owned unload frees process",
                    client.post("/developer/compute/unload", json={}).json()["effect"]
                    == "OWNED_SERVER_STOPPED",
                )
                check(
                    "unloaded generation unavailable",
                    client.post("/chat", json={"text": "Hello"}).status_code == 503,
                )
                check(
                    "explicit reload succeeds",
                    client.post("/developer/compute/load", json={}).json()["status"] == "HEALTHY",
                )
                check(
                    "finalized selection rolls back",
                    client.post("/developer/models/rollback", json={}).json()["status"]
                    == "ROLLED_BACK",
                )
                check(
                    "old model remains registered",
                    len(client.get("/developer/models").json()["profiles"]) == 2,
                )
                client.post("/auth/switch", json={"mode": "guest"})
                check(
                    "guest cannot manage models",
                    client.post("/developer/models/finalize", json={}).status_code == 403,
                )
        finally:
            server.should_exit = True
            thread.join(timeout=30)
            if thread.is_alive():
                raise RuntimeError("QA shutdown did not finish")
        check(
            "owned model process stopped on shutdown",
            app.state.models.manager.delegate.process is None,
        )
        for report in benchmarks:
            identifier = report["profile_id"]
            destination = (
                PROJECT / "docs/operations/evidence" / f"wave8-{identifier}-benchmark.json"
            )
            destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        result = {
            "version": APP_VERSION,
            "status": "PASS",
            "checks": len(passed),
            "passed": passed,
            "actual_hardware": profile(root),
            "qa_compute_policy": settings.compute.model_dump(),
            "model_files": [baseline.model_file, candidate.model_file],
            "note": "Real Vulkan Qwen/E5; temporary stores; no downloads or owner-data access.",
        }
        (PROJECT / "docs/operations/evidence/wave8-live-qa.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"status": "PASS", "checks": len(passed)}))


if __name__ == "__main__":
    main()
