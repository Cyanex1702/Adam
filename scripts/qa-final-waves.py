"""Exercise final-wave interfaces on an actual source/frozen desktop service."""

import argparse
import hashlib
import json
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import httpx
from adam import APP_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks = []

    def check(name, value):
        assert value, name
        checks.append(name)
        print("QA passed:", name, flush=True)

    with tempfile.TemporaryDirectory(prefix="adam-final-waves-qa-") as temporary:
        command = (
            [str(args.service.resolve())]
            if args.service
            else [sys.executable, "-m", "adam.desktop.service"]
        )
        child = subprocess.Popen(
            command + ["--probe", "--data-dir", temporary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(child.stdout.readline()), daemon=True).start()
            ready = json.loads(lines.get(timeout=150))
            with httpx.Client(
                base_url=f"http://127.0.0.1:{ready['port']}",
                headers={"x-adam-desktop": ready["nonce"]},
                timeout=120,
            ) as client:
                password = "synthetic-final-qa-owner-918274"
                check(
                    "personal routes need authentication",
                    client.get("/personal").status_code == 401,
                )
                check(
                    "owner setup",
                    client.post("/desktop/setup", json={"password": password}).status_code == 200,
                )
                check(
                    "owner login",
                    client.post("/auth/login", json={"password": password}).status_code == 200,
                )

                def chat(text):
                    response = client.post("/chat", json={"text": text})
                    response.raise_for_status()
                    result = response.json()
                    assert result["event_type"] == "agent.completed", result.get("event_type")
                    return result["payload"]

                memory = chat("/remember project cedar = Fictional Cedar uses Example Studio")[
                    "result"
                ]["memory"]
                value = {
                    "memory_id": memory["memory_id"],
                    "subject": "Cedar",
                    "relation": "uses",
                    "object": "Example Studio",
                }
                check(
                    "reviewed source-bound relationship",
                    client.post("/personal/link", json=value).status_code == 200,
                )
                graph = client.post("/personal/graph", json={"query": "Cedar"}).json()
                check(
                    "relationship explains actual source",
                    graph["links"][0]["source"]["content"] == memory["content"],
                )
                check(
                    "unrelated graph query abstains",
                    not client.post("/personal/graph", json={"query": "unrelated zebra"}).json()[
                        "links"
                    ],
                )
                check(
                    "unsupported entity denied",
                    client.post(
                        "/personal/link", json={**value, "object": "Unrecorded Company"}
                    ).status_code
                    == 409,
                )
                check(
                    "timeline includes recorded claim",
                    client.post("/personal/timeline", json={"query": "Cedar"}).json()["events"][0][
                        "memory_id"
                    ]
                    == memory["memory_id"],
                )
                chat("/correct cedar = Fictional Cedar uses Another Editor")
                check(
                    "source correction invalidates current link",
                    not client.post("/personal/graph", json={}).json()["links"],
                )
                historical = client.post("/personal/graph", json={"historical": True}).json()[
                    "links"
                ]
                check(
                    "historical source remains labeled",
                    historical[0]["source_status"] == "HISTORICAL",
                )
                check(
                    "naive timestamps refused",
                    client.post(
                        "/personal/timeline", json={"as_of": "2026-01-01T00:00:00"}
                    ).status_code
                    == 409,
                )
                check(
                    "personal chat command works without model",
                    "Recorded personal evidence" in chat("/graph Cedar")["text"],
                )
                chat("/forget cedar")
                check(
                    "forget cascades to historical graph",
                    not client.post("/personal/graph", json={"historical": True}).json()["links"],
                )
                goal = client.post(
                    "/personal/goal", json={"title": "Fictional QA goal", "project": "Cedar"}
                ).json()
                check("goal revision recorded", goal["revision"] == 1)
                check(
                    "stale goal edit refused",
                    client.post("/personal/goal", json={**goal, "revision": 0}).status_code == 409,
                )
                check(
                    "false completion refused",
                    client.post("/personal/goal", json={**goal, "status": "COMPLETED"}).status_code
                    == 409,
                )
                check(
                    "explicit goal completion",
                    client.post(
                        "/personal/goal", json={**goal, "status": "COMPLETED", "progress": 100}
                    ).status_code
                    == 200,
                )
                check(
                    "progress history survives reads",
                    len(client.get("/personal").json()["goals"][0]["history"]) == 2,
                )

                check("training needs owner elevation", client.get("/training").status_code == 403)
                client.post("/auth/elevate", json={"password": password}).raise_for_status()
                check("training defaults disabled", not client.get("/training").json()["enabled"])
                check(
                    "explicit experiment enable",
                    client.post("/training/configure", json={"enabled": True}).status_code == 200,
                )
                example = {
                    "category": "formatting",
                    "prompt": "Return a fictional color as JSON.",
                    "response": '{"color":"blue"}',
                    "approved": True,
                    "synthetic_behavior_only": True,
                    "permission_to_export": True,
                }
                check(
                    "unapproved training example denied",
                    client.post(
                        "/training/example", json={**example, "approved": False}
                    ).status_code
                    == 422,
                )
                check(
                    "credential-bearing example denied",
                    client.post(
                        "/training/example",
                        json={**example, "prompt": "password=fictional-secret-value-918274"},
                    ).status_code
                    == 409,
                )
                chat("/remember preference test editor = PrivateSyntheticEditor 18452")
                check(
                    "personal memory overlap denied",
                    client.post(
                        "/training/example",
                        json={**example, "response": "PrivateSyntheticEditor 18452"},
                    ).status_code
                    == 409,
                )
                check(
                    "approved synthetic behavior accepted",
                    client.post("/training/example", json=example).status_code == 200,
                )
                dataset = client.post("/training/dataset", json={}).json()
                check(
                    "exported dataset digest verified",
                    dataset["sha256"] == hashlib.sha256(dataset["jsonl"].encode()).hexdigest(),
                )
                check(
                    "dataset contains no owner memory",
                    "PrivateSyntheticEditor" not in dataset["jsonl"],
                )
                recipe = client.get("/training/recipe").json()
                check(
                    "GPU recipe honestly experimental",
                    recipe["status"] == "EXPERIMENTAL_NOT_EXECUTED",
                )
                compile(recipe["script"], "synthetic-recipe-check", "exec")
                check("recipe parses without running training", True)
                check(
                    "disabling revokes dataset access",
                    client.post("/training/configure", json={"enabled": False}).status_code == 200
                    and client.post("/training/dataset", json={}).status_code == 409,
                )
                client.post("/auth/logout").raise_for_status()
                check("logout revokes training routes", client.get("/training").status_code == 401)

                check(
                    "fictional demo grant",
                    client.post("/auth/session", json={"mode": "demo"}).status_code == 200,
                )
                check(
                    "demo memory cannot see owner",
                    not client.get("/memory", params={"query": "PrivateSyntheticEditor"}).json(),
                )
                demo = client.get("/personal").json()
                check(
                    "demo contains synthetic goals",
                    demo["goals"]
                    and all("Fictional QA goal" != item["title"] for item in demo["goals"]),
                )
                routine = demo["briefing"]["routine_candidates"][0]
                check(
                    "demo routine is inference with provenance",
                    routine["epistemic_status"] == "INFERRED" and len(routine["evidence_ids"]) >= 3,
                )
                check("demo cannot access training", client.get("/training").status_code == 403)
                check(
                    "demo cannot forge owner evidence",
                    client.post("/personal/link", json=value).status_code == 409,
                )
                check(
                    "demo note write verified",
                    client.post(
                        "/portfolio/demo-tool",
                        json={"action": "write_note", "text": "Fictional final QA note"},
                    ).json()["status"]
                    == "VERIFIED",
                )
                check(
                    "independent demo note inspection",
                    client.post("/portfolio/demo-tool", json={"action": "inspect"}).json()["text"]
                    == "Fictional final QA note",
                )
                check(
                    "demo note undo verified",
                    client.post("/portfolio/demo-tool", json={"action": "undo_note"}).json()[
                        "status"
                    ]
                    == "UNDONE",
                )
                check(
                    "arbitrary demo paths denied",
                    client.post(
                        "/portfolio/demo-tool", json={"action": "inspect", "path": "../../owner"}
                    ).status_code
                    == 422,
                )
                check(
                    "arbitrary demo execution denied",
                    client.post("/portfolio/demo-tool", json={"action": "shell.exec"}).status_code
                    == 422,
                )
                benchmark = client.get("/portfolio/benchmarks").json()
                check(
                    "bundled measured benchmark available",
                    benchmark["status"] == "MEASURED" and benchmark["release"] == APP_VERSION,
                )
                check(
                    "benchmark scope labels fixture transport",
                    "scripted" in benchmark["execution"] and len(benchmark["cases"]) == 22,
                )
                check(
                    "unavailable measurements remain null",
                    benchmark["vram_bytes"] is None and benchmark["voice_metrics"] is None,
                )
                client.post("/auth/session", json={"mode": "guest"}).raise_for_status()
                check("guest personal access denied", client.get("/personal").status_code == 403)
                check(
                    "guest cannot mutate demo sandbox",
                    client.post("/portfolio/demo-tool", json={"action": "write_note"}).status_code
                    == 403,
                )
        finally:
            if child.poll() is None:
                child.stdin.write("stop\n")
                child.stdin.flush()
                try:
                    child.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
        check("owned service stopped", child.returncode == 0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "release": APP_VERSION,
                "passed": True,
                "checks": checks,
                "target": "frozen" if args.service else "source",
                "limits": (
                    "Disposable profiles and scripted transport; "
                    "no GPU training or human acceptance."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"passed": True, "checks": len(checks)}))


if __name__ == "__main__":
    main()
