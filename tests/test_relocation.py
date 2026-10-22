import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode", ["relocated", "missing_custom", "existing_custom"])
def test_powershell_configuration_after_project_move(tmp_path, mode):
    shell = shutil.which("pwsh")
    if shell is None:
        pytest.skip("PowerShell required for startup configuration checks")
    root = tmp_path / "Project Adam"
    root.mkdir()
    config = root / "adam.compact.toml"
    config.write_text("[model]\n")
    old = tmp_path / "old" / ("Project Adam" if mode == "relocated" else "Other App")
    old_config = old / "adam.compact.toml"
    if mode == "existing_custom":
        old.mkdir(parents=True)
        old_config.write_text("[model]\n")
    env = {**os.environ, "ADAM_CONFIG": str(old_config), "ADAM_QA_ROOT": str(root)}
    helper = Path(__file__).resolve().parents[1] / "scripts" / "resolve-config.ps1"
    env["ADAM_QA_HELPER"] = str(helper)
    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-Command",
            "$ErrorActionPreference='Stop'; . $env:ADAM_QA_HELPER; "
            "Update-AdamConfigPath -ProjectRoot $env:ADAM_QA_ROOT; "
            "Write-Output $env:ADAM_CONFIG",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if mode == "missing_custom":
        assert result.returncode != 0
        assert "ADAM_CONFIG points to a missing file" in result.stderr
    else:
        assert result.returncode == 0
        assert result.stdout.strip().splitlines()[-1] == str(
            config if mode == "relocated" else old_config
        )
