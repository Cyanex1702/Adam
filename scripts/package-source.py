"""Assemble source-only and offline source/model ZIPs from a reviewed Git checkpoint."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import httpx
from adam import APP_VERSION
from adam.compute.hardware import assets_root
from adam.distribution.setup import FILES, PRESETS


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download_notice(url: str, target: Path) -> None:
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        response = client.get(url)
        response.raise_for_status()
    if len(response.content) > 1000000 or not response.text.strip():
        raise ValueError("Invalid upstream license response")
    target.write_bytes(response.content)


def zip_tree(root: Path, target: Path) -> None:
    pending = target.with_suffix(".zip.pending")
    with zipfile.ZipFile(
        pending, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as archive:
        for file in sorted(root.rglob("*")):
            if (
                any(
                    part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
                    for part in file.parts
                )
                or file.suffix == ".pyc"
            ):
                continue
            if file.is_symlink():
                raise ValueError("No links in a delivery package")
            if file.is_file():
                archive.write(
                    file,
                    file.relative_to(root.parent).as_posix(),
                    compress_type=zipfile.ZIP_STORED
                    if file.suffix == ".gguf"
                    else zipfile.ZIP_DEFLATED,
                )
    with zipfile.ZipFile(pending) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive CRC verification failed")
    pending.replace(target)
    print("Archive CRC verified:", target.name, flush=True)


def refresh_source(repo: Path, public: Path, full: Path) -> None:
    """Refresh final docs/QA tooling without recopying multi-gigabyte runtime assets."""
    manifest = json.loads((public / "SOURCE_MANIFEST.json").read_bytes())
    records = []
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")
    for name in names:
        if not name or name.startswith("docs/operations/evidence/"):
            continue
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid source path")
        source = repo / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError("Missing or linked source")
        if source.suffix.lower() in {
            ".gguf",
            ".exe",
            ".dll",
            ".pyd",
            ".sqlite3",
            ".adambak",
            ".adamportable",
            ".pem",
            ".key",
        }:
            raise ValueError("Forbidden runtime/private material in source refresh")
        raw = source.read_bytes()
        if source.suffix.lower() in {".md", ".json", ".txt"} and name != "LICENSE":
            text = raw.decode("utf-8-sig")
            for path, replacement in [
                (str(repo), "%PROJECT_ROOT%"),
                (str(Path.home()), "%USERPROFILE%"),
            ]:
                for variant in [path.replace("\\", "\\\\"), path, path.replace("\\", "/")]:
                    text = text.replace(variant, replacement)
            raw = text.encode("utf-8")
        if source.suffix.lower() == ".bat":
            raw = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        for stage in [public, full]:
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        records.append({"path": name, "sha256": sha(public / relative), "bytes": len(raw)})
    manifest["files"] = records
    manifest["source_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    for stage in [public, full]:
        (stage / "SOURCE_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    if sha(full / "LICENSE") != sha(repo / "LICENSE"):
        raise ValueError("License changed during source refresh")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage-only", action="store_true")
    parser.add_argument("--archive-existing", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    public = output / ("ADAM-" + APP_VERSION + "-GitHub")
    full = output / ("ADAM-" + APP_VERSION + "-Source-With-Model")
    github_zip = output / (public.name + ".zip")
    full_zip = output / (full.name + ".zip")
    if not args.archive_existing:
        if public.exists() or full.exists():
            raise ValueError("Choose a fresh output folder; existing stages are preserved")
        names = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
        copied, redacted = [], []
        for name in names:
            if not name or name.startswith("docs/operations/evidence/"):
                continue
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Invalid tracked source path")
            source = repo / relative
            if source.is_symlink() or not source.is_file():
                raise ValueError("Missing or linked tracked source")
            if source.suffix.lower() in {
                ".gguf",
                ".exe",
                ".dll",
                ".pyd",
                ".sqlite3",
                ".adambak",
                ".adamportable",
                ".pem",
                ".key",
            }:
                raise ValueError("Private/binary runtime material must not be tracked: " + name)
            target = public / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = source.read_bytes()
            if source.suffix.lower() in {".md", ".json", ".txt"} and name != "LICENSE":
                text = raw.decode("utf-8-sig")
                before = text
                for path, replacement in [
                    (str(repo), "%PROJECT_ROOT%"),
                    (str(Path.home()), "%USERPROFILE%"),
                ]:
                    for variant in [path.replace("\\", "\\\\"), path, path.replace("\\", "/")]:
                        text = text.replace(variant, replacement)
                if text != before:
                    redacted.append(name)
                raw = text.encode("utf-8")
            target.write_bytes(raw)
            copied.append({"path": name, "sha256": sha(target), "bytes": len(raw)})
        if sha(public / "LICENSE") != sha(repo / "LICENSE"):
            raise ValueError("User-supplied license must remain exact")
        for name in ["RUN_ADAM.bat", "RUN_DEMO.bat"]:
            path = public / name
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        # The hash manifest reflects the final CRLF batch files, not the checkout representation.
        for item in copied:
            item["sha256"] = sha(public / item["path"])
            item["bytes"] = (public / item["path"]).stat().st_size
        (public / "SOURCE_MANIFEST.json").write_text(
            json.dumps(
                {
                    "release": APP_VERSION,
                    "source_commit": commit,
                    "files": copied,
                    "redacted_document_paths": redacted,
                    "excluded": [
                        "Git history",
                        "owner data",
                        "machine-specific operational evidence",
                        "model weights",
                        "runtime binaries",
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        shutil.copytree(public, full)
        print("Reviewed source staged:", len(copied), "files", flush=True)
        # Copy only the interpreter installation and the dedicated ADAM environment.
        python_root = Path(sys.base_prefix)
        bundled = full / "runtime/python"
        bundled.mkdir(parents=True)
        for pattern in ["python*.exe", "python*.dll", "vcruntime*.dll", "LICENSE.txt"]:
            for file in python_root.glob(pattern):
                shutil.copy2(file, bundled / file.name)
        ignored = shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "site-packages",
            "test",
            "tests",
            "idlelib",
            "tkinter",
            "ensurepip",
        )
        shutil.copytree(python_root / "Lib", bundled / "Lib", ignore=ignored)
        shutil.copytree(
            python_root / "DLLs", bundled / "DLLs", ignore=shutil.ignore_patterns("*tk*", "*tcl*")
        )
        site = Path(sys.prefix) / "Lib/site-packages"

        def packages_ignore(directory: str, names: list[str]) -> list[str]:
            return [
                name
                for name in names
                if name
                in {"__pycache__", "tests", "test", "PyInstaller", "_pyinstaller_hooks_contrib"}
                or name.endswith(".pyc")
                or name.startswith("__editable__")
                or name == "direct_url.json"
                or (
                    name.endswith(".pth")
                    and name not in {"pywin32.pth", "distutils-precedence.pth"}
                )
            ]

        shutil.copytree(site, bundled / "Lib/site-packages", ignore=packages_ignore)
        model_name = "qwen3-4b-instruct"
        original = assets_root()
        model = original / ("models/" + model_name + ".gguf")
        if sha(model) != PRESETS[model_name][1]:
            raise ValueError("Installed model does not match the pinned accepted model")
        (full / "models").mkdir(exist_ok=True)
        shutil.copy2(model, full / "models" / model.name)
        shutil.copytree(original / "runtime/llama", full / "runtime/llama")
        download_notice(
            "https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/resolve/main/LICENSE",
            full / "models/LICENSE-Qwen.txt",
        )
        download_notice(
            "https://raw.githubusercontent.com/ggml-org/llama.cpp/b11146/LICENSE",
            full / "runtime/llama/LICENSE-llama.cpp.txt",
        )
        (full / "models/model-manifest.json").write_text(
            json.dumps(
                {
                    "model": "Qwen3-4B-Instruct-2507",
                    "quantization": "Q4_K_M",
                    "file": model.name,
                    "source": PRESETS[model_name][0] + FILES[model_name],
                    "sha256": sha(model),
                    "bytes": model.stat().st_size,
                    "license": "Apache-2.0",
                    "license_sha256": sha(full / "models/LICENSE-Qwen.txt"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if (full / "data").exists() or list(full.rglob("*.sqlite3")):
            raise ValueError("No runtime/private databases may enter the offline bundle")
        print("Offline Python, model and llama.cpp staged; no private data copied", flush=True)
        zip_tree(public, github_zip)
    if args.archive_existing:
        refresh_source(repo, public, full)
        zip_tree(public, github_zip)
    if args.stage_only:
        print(json.dumps({"stage": str(full), "github_zip": str(github_zip)}), flush=True)
        return
    if (full / "data").exists():
        raise ValueError("Run QA with an external disposable --data-dir, not delivery data")
    zip_tree(full, full_zip)
    artifacts = [
        {"file": file.name, "bytes": file.stat().st_size, "sha256": sha(file)}
        for file in [github_zip, full_zip]
    ]
    (output / "SOURCE-SHA256SUMS.txt").write_text(
        "".join(item["sha256"] + "  " + item["file"] + "\n" for item in artifacts), encoding="utf-8"
    )
    receipt = {
        "release": APP_VERSION,
        "source_stage": str(full),
        "artifacts": artifacts,
        "models_separate_folder": True,
        "private_data_included": False,
        "license": "Community Non-Commercial License v1.0",
    }
    (repo / "docs/operations/evidence/waves18-20-source-delivery.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
