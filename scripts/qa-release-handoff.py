"""Exercise the frozen offline activation helper and native restart with synthetic data."""

import argparse
import asyncio
import json
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path

import psutil
import win32api
import win32con
import win32job
from adam import APP_VERSION
from adam.core.config import Settings
from adam.core.runtime import ChatRequest, Runtime
from adam.distribution.releases import Releases, sha
from adam.evals.suite import ProbeProvider
from adam.security.auth import AuthManager


def members(job):
    result = []
    for p in psutil.process_iter(["name"]):
        if p.info["name"] not in {"adam-desktop.exe", "adam-service.exe"}:
            continue
        try:
            handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, p.pid)
            try:
                mine = win32job.IsProcessInJob(handle, job)
            finally:
                win32api.CloseHandle(handle)
            if mine:
                result.append(p)
        except (psutil.Error, win32api.error):
            pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--legacy-schema-six", action="store_true")
    args = parser.parse_args()
    checks = []

    def check(name, value):
        assert value, name
        checks.append(name)
        print("QA passed:", name, flush=True)

    with tempfile.TemporaryDirectory(prefix="adam-release-handoff-qa-") as temporary:
        home = Path(temporary) / "profile"
        settings = Settings(data_dir=home)
        settings.model.model_id = "handoff-offline-qa"
        settings.model.base_url = "http://127.0.0.1:65534"
        runtime = Runtime(settings, ProbeProvider())
        asyncio.run(
            runtime.chat(ChatRequest(text="/remember preference editor = HandoffSyntheticEditor"))
        )
        runtime.retrieval.close()
        if args.legacy_schema_six:
            # Only this disposable fixture is converted to the old release's schema.
            with closing(sqlite3.connect(home / "runtime.sqlite3")) as db, db:
                for table in [
                    "personal_goal_events",
                    "personal_goals",
                    "personal_links",
                    "training_examples",
                    "training_settings",
                ]:
                    db.execute("DROP TABLE " + table)
                db.execute("DELETE FROM schema_migrations WHERE version=7")
        auth = AuthManager(home)
        password = "synthetic-handoff-owner-834791"
        auth.initialize(password)
        token = auth.issue("owner", password)
        auth.elevate(token, password)
        manager = Releases(settings)
        staged = manager.stage(args.package, sha(args.package), "stable")
        ticket = manager.authorize(staged["id"], auth._hash(token))
        job = win32job.CreateJobObject(None, "")
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        # An already-exited synthetic parent makes this deterministic without touching native UI.
        parent = subprocess.Popen(
            ["cmd.exe", "/c", "exit", "0"], creationflags=subprocess.CREATE_NO_WINDOW
        )
        parent.wait(timeout=10)
        helper = subprocess.Popen(
            [str(args.baseline / "backend/adam-service.exe"), "--release-apply"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        win32job.AssignProcessToJobObject(job, int(helper._handle))
        owned = []
        try:
            payload = {
                "parent": parent.pid,
                "home": str(home),
                "data": str(home),
                "ticket": ticket["ticket"],
                "token": ticket["token"],
            }
            helper.stdin.write(json.dumps(payload))
            helper.stdin.close()
            helper.wait(timeout=240)
            check("frozen offline helper exits successfully", helper.returncode == 0)
            active = manager.state()["active"]
            check("helper publishes approved generation", active["id"] == staged["id"])
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                owned = members(job)
                if any(p.name() == "adam-desktop.exe" for p in owned) and any(
                    p.name() == "adam-service.exe" for p in owned
                ):
                    break
                time.sleep(0.2)
            check("helper restarts native UI and owned service", len(owned) >= 2)
            app, data = manager.entry(active)
            native = [p for p in owned if p.name() == "adam-desktop.exe"]
            check(
                "selected generation native executable runs",
                len(native) == 1
                and Path(native[0].exe()).resolve() == (app / "adam-desktop.exe").resolve(),
            )
            check("original data retained", (home / "runtime.sqlite3").is_file() and data != home)
        finally:
            win32api.CloseHandle(job)
            if helper.poll() is None:
                helper.wait(timeout=15)
            deadline = time.monotonic() + 15
            while any(p.is_running() for p in owned) and time.monotonic() < deadline:
                time.sleep(0.1)
            check("owned handoff processes cleaned", not any(p.is_running() for p in owned))
        if args.legacy_schema_six:
            with closing(sqlite3.connect(data / "runtime.sqlite3")) as db:
                check(
                    "legacy profile migrates to schema seven",
                    db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 7,
                )
            with closing(sqlite3.connect(home / "runtime.sqlite3")) as db:
                check(
                    "original schema six remains intact",
                    db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 6,
                )
            updated_auth = AuthManager(data)
            updated_token = updated_auth.issue("owner", password)
            updated_auth.elevate(updated_token, password)
            manager.settings = Settings.model_validate_json(
                (data / "config/restored-settings.json").read_bytes()
            )
            previous = manager.state()["previous"]
            approval = manager.authorize(
                previous["id"], updated_auth._hash(updated_token), "rollback"
            )
            result = manager.apply(approval["ticket"], approval["token"], args.baseline)
            check(
                "actual prior frozen release passes rollback probe",
                result["status"] == "ACTIVATED" and manager.state()["active"] == previous,
            )
            check("rollback selects original schema six data", manager.entry(previous)[1] == home)
    args.output.write_text(
        json.dumps(
            {
                "release": APP_VERSION,
                "passed": True,
                "checks": checks,
                "limits": (
                    "Synthetic owner and profile; no native UI input, "
                    "private data or external account."
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
