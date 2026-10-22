"""Native installed-host process/IPC/crash tests; no personal profiles or UI input."""

import argparse
import json
import os
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path

import httpx
import psutil
from adam import APP_VERSION


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks: list[str] = []

    def check(name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix="adam-native-host-qa-") as directory:
        root = Path(directory)
        marker = root / "synthetic-preservation.txt"
        marker.write_text("synthetic native QA marker", encoding="utf-8")
        # Deliberately unavailable external alias: this suite measures the native
        # bridge/lifecycle independently of scarce model resources and model QA.
        environment = dict(
            os.environ,
            ADAM_DATA_DIR=directory,
            ADAM_MODEL_ID="desktop-offline-qa",
            ADAM_MODEL_URL="http://127.0.0.1:65534",
        )
        for iteration in range(2):
            app = subprocess.Popen(
                [str(args.exe.resolve())],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            owned: list[psutil.Process] = []
            try:
                deadline = time.monotonic() + 150
                port = None
                while time.monotonic() < deadline:
                    if app.poll() is not None:
                        raise AssertionError("native host exited before frontend started backend")
                    owned = psutil.Process(app.pid).children(recursive=True)
                    services = [item for item in owned if item.name() == "adam-service.exe"]
                    if services:
                        for connection in services[0].net_connections(kind="tcp"):
                            if connection.status == psutil.CONN_LISTEN:
                                check(
                                    "loopback only " + str(iteration),
                                    connection.laddr.ip == "127.0.0.1",
                                )
                                port = connection.laddr.port
                                break
                    if port:
                        break
                    time.sleep(0.25)
                check("frontend boots owned service " + str(iteration), port is not None)
                with httpx.Client(timeout=10) as client:
                    response = client.get(f"http://127.0.0.1:{port}/desktop/status")
                    check(
                        "native capability remains private " + str(iteration),
                        response.status_code == 403,
                    )
                check(
                    "isolated native store " + str(iteration), (root / "runtime.sqlite3").is_file()
                )
                with closing(
                    sqlite3.connect((root / "runtime.sqlite3").as_uri() + "?mode=ro", uri=True)
                ) as database:
                    check(
                        "store integrity " + str(iteration),
                        database.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
                    )
                second = subprocess.Popen(
                    [str(args.exe.resolve())],
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    second.wait(timeout=20)
                    check(
                        "single instance " + str(iteration),
                        second.returncode == 0 and app.poll() is None,
                    )
                finally:
                    if second.poll() is None:
                        second.kill()
                        second.wait()
                owned = psutil.Process(app.pid).children(recursive=True)
            finally:
                if app.poll() is None:
                    app.kill()  # Deliberate parent crash exercises Windows job cleanup.
                app.wait(timeout=15)
                deadline = time.monotonic() + 15
                while any(item.is_running() for item in owned) and time.monotonic() < deadline:
                    time.sleep(0.1)
                leaked = [item for item in owned if item.is_running()]
                for item in leaked:
                    item.kill()
                check("parent crash cleans owned descendants " + str(iteration), not leaked)
            check(
                "preservation marker " + str(iteration),
                marker.read_text(encoding="utf-8") == "synthetic native QA marker",
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "release": APP_VERSION,
                "kind": "installed-native-host",
                "passed": len(checks),
                "checks": checks,
                "limits": "No native UI input or FPS measurement; real model tested separately.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Native desktop host: {len(checks)} checks passed")


if __name__ == "__main__":
    main()
