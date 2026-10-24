"""Package the paired release, verified against final sources and frozen bytecode."""

import argparse
import json
import shutil
import types
import zipfile
from pathlib import Path

from adam import APP_VERSION
from adam.distribution.releases import manifest, sha, verify
from PyInstaller.archive.readers import CArchiveReader


def canonical(code):
    return code.replace(
        co_filename="",
        co_consts=tuple(
            canonical(v) if isinstance(v, types.CodeType) else v for v in code.co_consts
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--waves", nargs="+", type=int, default=[18, 19, 20])
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)
    stage = args.output / ("ADAM-Desktop-" + APP_VERSION)
    if stage.exists():
        raise RuntimeError("Review the existing delivery stage before repackaging")
    native = args.build_dir / "adam-desktop.exe"
    raw = native.read_bytes()
    assert (
        raw.count(b"__TAURI_BUNDLE_TYPE_VAR_UNK") == 1 and b"__TAURI_BUNDLE_TYPE_VAR_NSS" not in raw
    )
    backend = repo / "apps/desktop/src-tauri/resources/backend"
    pyz = CArchiveReader(str(backend / "adam-service.exe")).open_embedded_archive("PYZ.pyz")
    modules = 0
    for source in (repo / "backend/adam").rglob("*.py"):
        relative = source.relative_to(repo / "backend").with_suffix("")
        pieces = list(relative.parts)
        if pieces[-1] == "__init__":
            pieces.pop()
        name = ".".join(pieces)
        assert canonical(pyz.extract(name)) == canonical(
            compile(source.read_bytes(), str(source), "exec", optimize=0)
        ), name
        modules += 1
    print("All frozen ADAM modules match final source:", modules, flush=True)
    stage.mkdir()
    sources = {"adam-desktop.exe": native, "adam.compact.toml": repo / "adam.compact.toml"}
    sources.update({name: repo / name for name in ["LICENSE", "THIRD_PARTY.md"]})
    for name in ["diagnostics", "model-library"]:
        sources[name + ".md"] = repo / "docs/operations" / (name + ".md")
    for name in [
        "computer-actions",
        "distribution",
        "personal-intelligence",
        "behavior-training",
        "portfolio",
    ]:
        sources[name + ".md"] = repo / "docs/operations" / (name + ".md")
    for name, source in sources.items():
        shutil.copy2(source, stage / name)
    shutil.copytree(backend, stage / "backend")
    for file in backend.rglob("*"):
        if file.is_file():
            sources[str(Path("backend") / file.relative_to(backend))] = file
    for name, source in sources.items():
        assert sha(stage / name) == sha(source), name
    (stage / "Launch-ADAM.cmd").write_bytes(
        b'@echo off\r\n"%~dp0backend\\adam-service.exe" --release-launch\r\n'
    )
    (stage / "README.txt").write_text(
        "ADAM Desktop "
        + APP_VERSION
        + (
            " - Combined final implementation\n"
            "Extract the entire folder, then open adam-desktop.exe "
            "or Launch-ADAM.cmd. Models and personal stores are external. "
            "Read portfolio.md and distribution.md. "
            "Human acceptance remains pending; no validated fine-tuned adapter is included.\n"
        ),
        encoding="utf-8",
    )
    (stage / "release.json").write_text(
        json.dumps(manifest(stage, APP_VERSION), indent=2) + "\n", encoding="utf-8"
    )
    verify(stage)
    files = [p for p in stage.rglob("*") if p.is_file()]
    assert not list(stage.rglob("*.gguf")) and not list(stage.rglob("*.sqlite3"))
    archives = []
    for filename, portable in [
        ("ADAM-Desktop-" + APP_VERSION + "-portable.zip", True),
        ("ADAM-Desktop-" + APP_VERSION + ".adamrelease.zip", False),
    ]:
        target = args.output / filename
        pending = target.with_suffix(target.suffix + ".pending")
        with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for file in sorted(files):
                archive.write(
                    file, file.relative_to(stage.parent if portable else stage).as_posix()
                )
        with zipfile.ZipFile(pending) as archive:
            assert archive.testzip() is None and len(archive.infolist()) == len(files)
        pending.replace(target)
        archives.append(target)
        print("Archive CRC passed:", filename, flush=True)
    installer = args.build_dir / "bundle/nsis" / ("ADAM Desktop_" + APP_VERSION + "_x64-setup.exe")
    shutil.copy2(installer, args.output / installer.name)
    artifacts = [
        {"path": str(p), "bytes": p.stat().st_size, "sha256": sha(p)}
        for p in [args.output / installer.name, *archives]
    ]
    (args.output / "SHA256SUMS.txt").write_text(
        "".join(v["sha256"] + "  " + Path(v["path"]).name + "\n" for v in artifacts),
        encoding="utf-8",
    )
    receipt = {
        "release": APP_VERSION,
        "waves": args.waves,
        "frozen_source_modules": modules,
        "frozen_source_parity": "PASSED",
        "source_file_comparison": "PASSED",
        "archive_crc": "PASSED",
        "portable_files": len(files),
        "models_and_private_stores": "EXCLUDED",
        "artifacts": artifacts,
    }
    evidence_name = (
        "waves18-20-delivery.json"
        if APP_VERSION == "0.20.0"
        else "repair-" + APP_VERSION.replace(".", "") + "-delivery.json"
    )
    evidence_dir = args.output / "qa"
    evidence_dir.mkdir(exist_ok=True)
    (evidence_dir / evidence_name).write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
