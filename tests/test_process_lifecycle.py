import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest
from adam.compute.process_guard import ChildGuard


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel job guarantee")
def test_forced_host_exit_reaps_child_and_preserves_unrelated_process(tmp_path):
    sentinel = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys,time;from adam.compute.process_guard import ChildGuard;"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            "guard=ChildGuard(child);print(child.pid,flush=True);time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child = None
    try:
        child = psutil.Process(int(parent.stdout.readline().strip()))
        parent.kill()  # Finally/atexit cannot run.
        parent.wait(timeout=10)
        deadline = time.monotonic() + 10
        while child.is_running() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not child.is_running()
        assert sentinel.poll() is None
    finally:
        for process in [parent, sentinel]:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
        if child and child.is_running():
            child.kill()


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel job guarantee")
def test_guard_failure_stops_owned_child(monkeypatch):
    import win32job

    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    monkeypatch.setattr(
        win32job,
        "AssignProcessToJobObject",
        lambda *args: (_ for _ in ()).throw(OSError("synthetic")),
    )
    with pytest.raises(ValueError, match="MODEL.PROCESS_GUARD_FAILED"):
        ChildGuard(child)
    assert child.poll() is not None


def test_source_launcher_uses_runtime_ownership():
    text = (Path(__file__).parents[1] / "scripts/start.ps1").read_text()
    assert "Start-Process" not in text
    assert "ADAM_MANAGED_SOURCE" in text
