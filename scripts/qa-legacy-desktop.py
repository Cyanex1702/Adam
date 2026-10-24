"""Exercise real legacy databases against the frozen service, using synthetic inference."""

import argparse
import json
import queue
import sqlite3
import subprocess
import tempfile
import threading
from contextlib import closing, contextmanager
from pathlib import Path

import httpx
from adam import APP_VERSION
from adam.core.migrations import MIGRATIONS, migrate
from adam.security.auth import AuthManager

PASSWORD = "synthetic-legacy-desktop-test-password"


@contextmanager
def service(executable, root):
    child = subprocess.Popen(
        [str(executable.resolve()), "--probe", "--data-dir", str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        receipts = queue.Queue()
        threading.Thread(target=lambda: receipts.put(child.stdout.readline()), daemon=True).start()
        receipt = json.loads(receipts.get(timeout=90))
        assert receipt["event"] == "ready", receipt.get("error")
        with httpx.Client(
            base_url=f"http://127.0.0.1:{receipt['port']}",
            headers={"x-adam-desktop": receipt["nonce"]},
            timeout=30,
        ) as client:
            yield client
    finally:
        child.stdin.close()
        try:
            child.wait(timeout=25)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            raise AssertionError("Frozen service did not stop on EOF") from None
        assert child.returncode == 0


def seed(root, version):
    root.mkdir(parents=True)
    path = root / "runtime.sqlite3"
    if version:
        migrate(path, MIGRATIONS[:version])
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("INSERT INTO runtime_metadata VALUES ('legacy-sentinel','preserved')")
            if version >= 2:
                db.execute(
                    "INSERT INTO sessions(session_id,created_at,updated_at) VALUES (?,?,?)",
                    ("legacy-session", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
                )
                db.execute(
                    "INSERT INTO turns(session_id,user_text,assistant_text,created_at,trace_id,"
                    "model_id) VALUES (?,?,?,?,?,?)",
                    (
                        "legacy-session",
                        "Synthetic legacy question",
                        "Synthetic legacy answer",
                        "2026-01-01T00:00:00Z",
                        "legacy-trace",
                        "synthetic-model",
                    ),
                )
    AuthManager(root).initialize(PASSWORD)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="adam-legacy-frozen-") as directory:
        base = Path(directory)
        if args.baseline:
            for version in range(1, 6):
                root = base / f"baseline-{version}"
                path = seed(root, version)
                before = path.read_bytes()
                with service(args.baseline, root) as client:
                    status = client.get("/desktop/status").json()
                    assert status["recovery"] is True
                    assert "STORAGE.INTEGRITY_FAILED" in status["issues"]
                assert path.read_bytes() == before
                results.append(f"0.20.1 false corruption reproduced at real schema {version}")
        for version in range(8):
            root = base / f"final-{version}"
            path = seed(root, version)
            with closing(sqlite3.connect(root / "security/auth.sqlite3")) as db:
                credential = db.execute("SELECT salt,digest FROM credential").fetchone()
            with service(args.service, root) as client:
                status = client.get("/desktop/status").json()
                assert status["release"] == APP_VERSION
                assert status["recovery"] is False
                assert status["configured"] is True
                assert client.post("/auth/login", json={"password": PASSWORD}).status_code == 200
                report = client.get("/desktop/diagnostics").json()
                assert report["storage"]["schemas"]["runtime.sqlite3"] == 7
                assert report["storage"]["stores"]["runtime.sqlite3"] == "HEALTHY"
                assert str(root) not in json.dumps(report)
                assert "Synthetic legacy question" not in json.dumps(report)
            with closing(sqlite3.connect(root / "security/auth.sqlite3")) as db:
                assert db.execute("SELECT salt,digest FROM credential").fetchone() == credential
            with closing(sqlite3.connect(path)) as db:
                assert db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 7
                if version:
                    assert (
                        db.execute("SELECT value FROM runtime_metadata").fetchone()[0]
                        == "preserved"
                    )
                if version >= 2:
                    assert db.execute("SELECT user_text,assistant_text FROM turns").fetchall() == [
                        ("Synthetic legacy question", "Synthetic legacy answer")
                    ]
            results.append(
                f"schema {version}: login, migration, credentials, history, diagnostics, EOF passed"
            )
        for kind, code in [
            ("corrupt", "STORAGE.INTEGRITY_FAILED"),
            ("layout", "STORAGE.SCHEMA_MISMATCH"),
            ("checksum", "STORAGE.UNSUPPORTED_SCHEMA"),
        ]:
            root = base / kind
            path = seed(root, 7)
            if kind == "corrupt":
                path.write_bytes(b"synthetic invalid SQLite database")
            else:
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(
                        "DROP TABLE knowledge_chunks"
                        if kind == "layout"
                        else "UPDATE schema_migrations SET checksum='synthetic-drift' "
                        "WHERE version=7"
                    )
            before = path.read_bytes()
            with service(args.service, root) as client:
                assert client.get("/desktop/status").json()["recovery"] is True
                report = client.get("/desktop/diagnostics").json()
                assert report["storage"]["stores"]["runtime.sqlite3"] == code
                assert str(root) not in json.dumps(report)
            assert path.read_bytes() == before
            results.append(f"{kind}: correct diagnosis and original database preserved")
    value = {
        "release": APP_VERSION,
        "kind": "frozen-real-schema-upgrade-matrix",
        "passed_scenarios": len(results),
        "scenarios": results,
        "inference": "synthetic; actual frozen process, SQLite files and authentication",
    }
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value), flush=True)


if __name__ == "__main__":
    main()
