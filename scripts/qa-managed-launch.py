"""Check direct-EXE managed launch in a synthetic home, with an owned Windows job."""

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

import psutil
import win32api
import win32con
import win32job
from adam import APP_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks = []

    def check(name, value):
        assert value, name
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix="adam-managed-launch-qa-") as temporary:
        root = Path(temporary)
        environment = dict(
            os.environ,
            ADAM_HOME=str(root),
            ADAM_MODEL_ID="managed-offline-qa",
            ADAM_MODEL_URL="http://127.0.0.1:65534",
        )
        for key in ["ADAM_DATA_DIR", "ADAM_MANAGED_LAUNCH", "ADAM_CONFIG", "ADAM_RESTORED_CONFIG"]:
            environment.pop(key, None)
        job = win32job.CreateJobObject(None, "")
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        driver = subprocess.Popen(
            [str(args.exe.resolve())],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        win32job.AssignProcessToJobObject(job, int(driver._handle))
        owned = []
        try:
            driver.wait(timeout=120)
            check("direct EXE dispatches managed launcher", driver.returncode == 0)
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                owned = []
                for process in psutil.process_iter(["name"]):
                    if process.info["name"] not in {"adam-desktop.exe", "adam-service.exe"}:
                        continue
                    try:
                        handle = win32api.OpenProcess(
                            win32con.PROCESS_QUERY_INFORMATION, False, process.pid
                        )
                        try:
                            mine = win32job.IsProcessInJob(handle, job)
                        finally:
                            win32api.CloseHandle(handle)
                        if mine:
                            owned.append(process)
                    except (psutil.Error, win32api.error):
                        pass
                if (root / "runtime.sqlite3").is_file() and len(owned) >= 2:
                    break
                time.sleep(0.1)
            check("managed native window and owned service start", len(owned) >= 2)
            check("managed home receives isolated data", (root / "runtime.sqlite3").is_file())
            check("generation state folder exists", (root / "distribution").is_dir())
            check(
                "no relaunch loop", len([p for p in owned if p.name() == "adam-desktop.exe"]) == 1
            )
        finally:
            win32api.CloseHandle(job)
            deadline = time.monotonic() + 15
            while any(p.is_running() for p in owned) and time.monotonic() < deadline:
                time.sleep(0.1)
            check("owned managed processes stop", not any(p.is_running() for p in owned))
    args.output.write_text(
        json.dumps(
            {
                "release": APP_VERSION,
                "passed": True,
                "checks": checks,
                "limits": "Synthetic home; no personal profile or UI input.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"passed": True, "checks": len(checks)}))


if __name__ == "__main__":
    main()
