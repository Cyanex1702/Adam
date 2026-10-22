"""Loopback HTTP, restore, export and terminal recovery QA in temporary fixtures.

Use --real-model with the configured local llama server already running. This
script never starts/stops a user server or reads the owner's personal store.
"""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from adam import APP_VERSION
from adam.api.app import create_app
from adam.core.config import load_settings
from adam.evals.suite import ProbeProvider
from adam.resilience.restore import rebuild_indexes

PROJECT = Path(__file__).resolve().parents[1]
OWNER = "synthetic-wave7-owner-passphrase-827139"
PASSWORD = "synthetic-wave7-backup-passphrase-372819"


@contextmanager
def serving(settings, real_model):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    app = create_app(settings, None if real_model else ProbeProvider())
    if hasattr(app.state, "auth") and not app.state.auth.configured():
        app.state.auth.initialize(OWNER)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_level="error")
    )
    thread = threading.Thread(target=server.run)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("QA API startup failed")
            time.sleep(0.1)
        else:
            raise RuntimeError("QA API startup timed out")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=180) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        if thread.is_alive():
            raise RuntimeError("QA API shutdown failed")


def hashes(root):
    return {
        file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in root.rglob("*")
        if file.is_file()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-model", action="store_true")
    args = parser.parse_args()
    passed = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        passed.append(name)

    def login(client):
        check(
            "owner login", client.post("/auth/login", json={"password": OWNER}).status_code == 200
        )
        check(
            "fresh owner elevation",
            client.post("/auth/elevate", json={"password": OWNER}).status_code == 200,
        )

    with TemporaryDirectory(prefix="adam-wave7-live-") as temporary:
        fixture = Path(temporary)
        root = fixture / "source"
        settings = load_settings(PROJECT / "adam.compact.toml", env={})
        settings.data_dir = root
        settings.knowledge.allowed_roots = [root]
        settings.model.max_tokens = 120
        settings.model.temperature = 0
        settings.consolidation_interval_seconds = 3600
        with serving(settings, args.real_model) as client:
            check(
                "anonymous maintenance denied",
                client.get("/maintenance/backups").status_code == 401,
            )
            client.post("/auth/login", json={"password": OWNER})
            check(
                "unelevated backup denied",
                client.post("/maintenance/backups", json={"password": PASSWORD}).status_code == 403,
            )
            login(client)
            response = client.post(
                "/chat", json={"text": "/remember preference editor = SnapshotStudio"}
            )
            check("memory fixture saved", response.status_code == 200)
            client.post("/chat", json={"text": "/remember project Cedar = uses Rust"})
            source = root / "cedar.md"
            source.write_text(
                "Fictional Cedar launch command: cedar serve --port 9123.\n", encoding="utf-8"
            )
            ingested = client.post(
                "/knowledge/sources", json={"path": str(source), "namespace": "Cedar"}
            )
            check("canonical source ingested", ingested.status_code == 200)
            indexed = client.post("/knowledge/reindex")
            check("source index rebuilt", indexed.status_code == 200)
            if args.real_model:
                check(
                    "real E5 semantic index available",
                    indexed.json().get("chunks", 0) > 0,
                )
                reply = client.post("/chat", json={"text": "Which editor do I prefer?"})
                check("real Qwen recalls original memory", "SnapshotStudio" in reply.text)
            action = client.post(
                "/tools/preview",
                json={
                    "name": "notes.create",
                    "arguments": {"path": "pending.txt", "text": "synthetic pending work"},
                },
            ).json()
            client.post(
                f"/actions/{action['action_id']}/approve", json={"digest": action["digest"]}
            )
            backup = client.post(
                "/maintenance/backups", json={"password": PASSWORD, "generation": "milestone"}
            )
            check("live encrypted snapshot created", backup.status_code == 200)
            identifier = backup.json()["backup_id"]
            verified = client.post(
                f"/maintenance/backups/{identifier}/verify", json={"password": PASSWORD}
            )
            check(
                "archive verifies and excludes vault",
                verified.status_code == 200 and verified.json()["vault_included"] is False,
            )
            archive = client.get(f"/maintenance/backups/{identifier}/download")
            check(
                "download is encrypted",
                archive.content.startswith(b"ADAMBK01")
                and b"SnapshotStudio" not in archive.content,
            )
            wrong = client.post(
                f"/maintenance/backups/{identifier}/verify",
                json={"password": "different-synthetic-passphrase"},
            )
            check(
                "wrong passphrase fails closed",
                wrong.status_code == 409 and "AUTHENTICATION_FAILED" in wrong.text,
            )
            client.post("/chat", json={"text": "/correct editor = ChangedAfterSnapshot"})
            source.unlink()
            restored = client.post(
                f"/maintenance/backups/{identifier}/restore", json={"password": PASSWORD}
            )
            check(
                "isolated restore succeeds",
                restored.status_code == 200 and restored.json()["status"] == "VERIFIED",
            )
            target = Path(restored.json()["target"])
            check("restore uses fresh destination", target != root and target.is_dir())
            check("vault absent by default", not (target / "security/vault.sqlite3").exists())
            check(
                "pending write never replayed", not (target / "tool-sandbox/pending.txt").exists()
            )
            exported = client.post("/maintenance/exports", json={"project": "Cedar"})
            check(
                "project export verified",
                exported.status_code == 200 and exported.json()["integrity"] == "VERIFIED",
            )
            export_id = exported.json()["export_id"]
            for name in [
                "data.json",
                "data.jsonl",
                "summary.md",
                "records.csv",
                "export-manifest.json",
            ]:
                data = client.get(f"/maintenance/exports/{export_id}/{name}")
                check(
                    f"download {name} excludes credentials",
                    data.status_code == 200
                    and OWNER not in data.text
                    and PASSWORD not in data.text,
                )
            check(
                "export download allowlist",
                client.get(f"/maintenance/exports/{export_id}/auth.sqlite3").status_code == 409,
            )
            client.post("/auth/switch", json={"mode": "guest"})
            check(
                "guest cannot export owner data",
                client.post("/maintenance/exports", json={}).status_code == 403,
            )
        restored_settings = load_settings(env={"ADAM_DATA_DIR": str(target)})
        with serving(restored_settings, args.real_model) as client:
            check(
                "old capability absent after restore",
                client.get("/maintenance/backups").status_code == 401,
            )
            login(client)
            memory = client.post("/chat", json={"text": "/show memory editor"})
            check(
                "point in time memory restored",
                "SnapshotStudio" in memory.text and "ChangedAfterSnapshot" not in memory.text,
            )
            pending = client.get(f"/actions/{action['action_id']}").json()
            check(
                "restored approval invalidated",
                pending["approved_until"] == 0 and pending["result"]["status"] == "UNCERTAIN",
            )
            evidence = client.post(
                "/knowledge/retrieve", json={"query": "Cedar launch command", "namespace": "Cedar"}
            )
            check(
                "portable source retrieval without original file",
                evidence.status_code == 200
                and "9123" in evidence.text
                and str(root / "cedar.md") not in evidence.text,
            )
            if args.real_model:
                check("restored retrieval uses real E5", evidence.json()["mode"] == "HYBRID")
                reply = client.post("/chat", json={"text": "Which editor do I prefer?"})
                check("real Qwen recalls restored memory", "SnapshotStudio" in reply.text)
        # Offline repair touches only this script's temporary derived index.
        vectors = target / "knowledge/vectors"
        vectors.mkdir(parents=True, exist_ok=True)
        (vectors / "meta.json").write_text("synthetic derived corruption", encoding="utf-8")
        rebuilt = rebuild_indexes(restored_settings)
        check(
            "offline repair quarantines previous index",
            rebuilt["quarantined_previous_index"] is True,
        )
        check(
            "offline repair retains canonical source", rebuilt["canonical_sources_retained"] is True
        )
        if args.real_model:
            check("offline E5 rebuild needs no LLM", rebuilt["chunks"] > 0)
        (target / "tasks.sqlite3").write_bytes(b"synthetic core integrity fault")
        before = hashes(target)
        with serving(restored_settings, args.real_model) as client:
            check(
                "corrupt core enters recovery",
                client.get("/health").json()["status"] == "RECOVERY_READ_ONLY",
            )
            check(
                "recovery blocks chat writes",
                client.post("/chat", json={"text": "/forget editor"}).status_code == 503,
            )
            check("recovery blocks private HTTP data", client.get("/memory").status_code == 503)
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("ADAM_")
        }
        command = [sys.executable, "-m", "adam.resilience.cli", "--data-dir", str(target)]
        terminal = subprocess.run(
            [*command, "recovery"], capture_output=True, text=True, env=environment, timeout=30
        )
        check(
            "terminal recovery needs no model or authentication",
            terminal.returncode == 0
            and json.loads(terminal.stdout)["session_mode"] == "RECOVERY_READ_ONLY",
        )
        salvage = fixture / "salvage"
        terminal = subprocess.run(
            [*command, "export", str(salvage), "--recovery"],
            capture_output=True,
            text=True,
            env=environment,
            timeout=30,
        )
        check(
            "terminal salvage marks partial export",
            terminal.returncode == 0 and json.loads(terminal.stdout)["status"] == "PARTIAL",
        )
        check("recovery preserved every source file byte", hashes(target) == before)
    report = {
        "version": APP_VERSION,
        "status": "PASS",
        "checks": len(passed),
        "passed": passed,
        "real_model": args.real_model,
        "filesystem": "isolated synthetic local PC stores",
    }
    name = "wave7-real-model-qa.json" if args.real_model else "wave7-live-qa.json"
    destination = PROJECT / "docs/operations/evidence" / name
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "checks": len(passed), "real_model": args.real_model}))


if __name__ == "__main__":
    main()
