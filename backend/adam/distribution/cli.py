"""Frozen, Python-free managed launcher and bounded offline activation helper."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil  # type: ignore[import-untyped]

from adam.core.config import Settings, resolve_data_dir
from adam.distribution.portable import DistributionError
from adam.distribution.releases import Releases


def launch(home: Path, baseline: Path) -> None:
    manager = Releases(Settings(data_dir=home), home)
    try:
        active = manager.state()["active"]
        if active:
            app, data = manager.entry(active)
        else:
            app, data = baseline, home
    except (ValueError, OSError, KeyError, TypeError):
        # Preserve the damaged pointer for diagnosis; the original profile is retained.
        state_path = manager.root / "state.json"
        if state_path.exists():
            state_path.rename(
                state_path.with_name("state-quarantine-" + str(time.time_ns()) + ".json")
            )
        from adam.distribution.portable import publish

        publish(
            manager.root / "state.json", json.dumps({"active": None, "previous": None}).encode()
        )
        publish(
            manager.root / "last-result.json",
            json.dumps(
                {
                    "status": "RECOVERY_FALLBACK",
                    "error": "UPDATE.POINTER_INVALID",
                    "note": "Original profile opened; managed generations retained.",
                }
            ).encode(),
        )
        app, data = baseline, home
    env = dict(os.environ, ADAM_HOME=str(home), ADAM_DATA_DIR=str(data), ADAM_MANAGED_LAUNCH="1")
    env.pop("ADAM_RESTORED_CONFIG", None)
    restored = data / "config/restored-settings.json"
    # Native host passes this to the frozen sidecar; no original model is required for setup.
    if restored.is_file():
        env["ADAM_RESTORED_CONFIG"] = str(restored)
    subprocess.Popen(
        [str(app / "adam-desktop.exe")],
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def main() -> None:
    baseline = Path(sys.executable).resolve().parent.parent
    if sys.argv[1:] == ["--release-launch"]:
        launch(Path(os.environ.get("ADAM_HOME", str(resolve_data_dir()))), baseline)
        return
    data: dict[str, Any] = json.loads(sys.stdin.readline(16384))
    deadline = time.monotonic() + 45
    while psutil.pid_exists(data["parent"]):
        if time.monotonic() > deadline:
            raise DistributionError("UPDATE.CLOSE_REQUIRED")
        time.sleep(0.1)
    home, current = Path(data["home"]), Path(data["data"])
    manager = Releases(Settings(data_dir=current), home)
    import re

    if not re.fullmatch(r"[a-f0-9-]{36}", data["ticket"]):
        raise DistributionError("UPDATE.ID_INVALID")
    record = json.loads((manager.root / "tickets" / (data["ticket"] + ".json")).read_bytes())
    manager.settings = Settings.model_validate(record["settings"])
    try:
        manager.apply(data["ticket"], data["token"], baseline)
    finally:
        launch(home, baseline)
