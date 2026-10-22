"""Verify current-user upgrade preserves existing stores and public model assets."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import psutil
from adam import APP_VERSION


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_matches(installed: Path, built: Path) -> bool:
    actual, expected = installed.read_bytes(), built.read_bytes()
    # Tauri restores the portable build's UNK tag after embedding NSS in NSIS.
    # Normalize only this one exact three-byte bundle discriminator.
    nsis, portable = b"__TAURI_BUNDLE_TYPE_VAR_NSS", b"__TAURI_BUNDLE_TYPE_VAR_UNK"
    return (
        actual.count(nsis) == expected.count(portable) == 1
        and actual.replace(nsis, portable, 1) == expected
    )


def snapshot(root: Path) -> dict[str, tuple[int, int, str | None]]:
    files = [root / "runtime.sqlite3", root / "security/auth.sqlite3"]
    for folder in ["mesh", "voice", "operations"]:
        if (root / folder).is_dir():
            files.extend(path for path in (root / folder).rglob("*") if path.is_file())
    if (root / "models").is_dir():
        files.extend((root / "models").rglob("*.gguf"))
    if (root / "models/voice").is_dir():
        files.extend(path for path in (root / "models/voice").rglob("*") if path.is_file())
    return {
        str(path): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            digest(path) if path.suffix == ".sqlite3" else None,
        )
        for path in files
        if path.is_file()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if any(p.name() == "adam-desktop.exe" for p in psutil.process_iter()):
        raise RuntimeError("Close ADAM Desktop before running upgrade QA")
    repo = Path(__file__).resolve().parents[1]
    local = Path(os.environ["LOCALAPPDATA"])
    before = snapshot(local / "ADAM")
    assert before, "No existing preservation fixtures found"
    process = subprocess.run(
        [str(args.installer.resolve()), "/S"],
        check=True,
        timeout=240,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    installed = (local / "ADAM Desktop").resolve()
    checks = []

    def check(name: str, condition: bool) -> None:
        assert condition, name
        checks.append(name)

    check("silent current-user upgrade exits cleanly", process.returncode == 0)
    check(
        "existing database hashes and model metadata preserved", before == snapshot(local / "ADAM")
    )
    check(
        "installed backend matches verified frozen service",
        digest(installed / "backend/adam-service.exe")
        == digest(repo / "apps/desktop/src-tauri/resources/backend/adam-service.exe"),
    )
    check(
        "installed native matches final build except exact NSIS bundle discriminator",
        native_matches(
            installed / "adam-desktop.exe",
            local / "ADAM/desktop-build/target/release/adam-desktop.exe",
        ),
    )
    check(
        "installed compact configuration preserved exactly",
        digest(installed / "adam.compact.toml") == digest(repo / "adam.compact.toml"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "release": APP_VERSION,
                "kind": "installed-upgrade",
                "passed": len(checks),
                "checks": checks,
                "preserved_files": len(before),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Installed upgrade: {len(checks)} checks passed")


if __name__ == "__main__":
    main()
