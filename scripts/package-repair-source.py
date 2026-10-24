"""Reuse the accepted offline assets while publishing current, reviewed source files."""

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

from adam import APP_VERSION


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path)
    parser.add_argument(
        "--source-only", action="store_true", help="Build only the GitHub source ZIP"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.source_only and args.base is None:
        parser.error("--base is required when bundling offline assets")
    repo = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)
    prefix = "ADAM-" + APP_VERSION
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0")
    source = {}
    for name in names:
        if not name or name.startswith("docs/operations/evidence/"):
            continue
        path = repo / name
        if (
            path.is_symlink()
            or not path.is_file()
            or path.suffix.lower()
            in {
                ".gguf",
                ".exe",
                ".dll",
                ".pyd",
                ".sqlite3",
                ".pem",
                ".key",
                ".adambak",
                ".adamportable",
            }
        ):
            raise ValueError("Forbidden source material")
        raw = path.read_bytes()
        if path.suffix.lower() in {".md", ".txt", ".json"} and name != "LICENSE":
            content = raw.decode("utf-8-sig")
            for old, new in [(str(repo), "%PROJECT_ROOT%"), (str(Path.home()), "%USERPROFILE%")]:
                for variant in [old.replace("\\", "\\\\"), old, old.replace("\\", "/")]:
                    content = content.replace(variant, new)
            raw = content.encode("utf-8")
        if path.suffix.lower() in {".bat", ".cmd"}:
            raw = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        source[name] = raw
    manifest = {
        "release": APP_VERSION,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip(),
        "files": [
            {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in sorted(source.items())
        ],
        "excluded": ["Git history", "owner data", "machine-specific evidence"],
        "offline_assets": (
            "Excluded from this source-only package"
            if args.source_only
            else "Reused unchanged from the accepted offline bundle"
        ),
    }
    source["SOURCE_MANIFEST.json"] = json.dumps(manifest, indent=2).encode()
    github = args.output / (prefix + "-GitHub.zip")
    full = args.output / (prefix + "-Source-With-Model.zip")
    packages = [(github, "GitHub")]
    if not args.source_only:
        packages.append((full, "Source-With-Model"))
    for target, flavor in packages:
        if target.exists():
            raise ValueError("Preserve the existing delivery; use a fresh output directory")
        pending = target.with_suffix(".zip.pending")
        root = prefix + "-" + flavor + "/"
        with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, raw in sorted(source.items()):
                archive.writestr(root + name, raw)
            if flavor == "Source-With-Model":
                with zipfile.ZipFile(args.base) as original:
                    for item in original.infolist():
                        relative = item.filename.partition("/")[2]
                        if item.is_dir() or not relative.startswith(("runtime/", "models/")):
                            continue
                        if relative in source:
                            continue
                        if any(
                            part.startswith("adam_runtime-") and part.endswith(".dist-info")
                            for part in Path(relative).parts
                        ):
                            continue
                        if ".." in Path(relative).parts or relative.startswith("/"):
                            raise ValueError("Invalid asset path")
                        record = zipfile.ZipInfo(root + relative, item.date_time)
                        record.compress_type = (
                            zipfile.ZIP_STORED
                            if relative.endswith(".gguf")
                            else zipfile.ZIP_DEFLATED
                        )
                        with (
                            original.open(item) as reader,
                            archive.open(record, "w", force_zip64=True) as writer,
                        ):
                            shutil.copyfileobj(reader, writer, 1024 * 1024)
                distribution = importlib.metadata.distribution("adam-runtime")
                if distribution.version != APP_VERSION:
                    raise ValueError("Update the local ADAM package metadata before packaging")
                for file in distribution.files or []:
                    parts = file.parts
                    if (
                        not parts
                        or not parts[0].startswith("adam_runtime-")
                        or not parts[0].endswith(".dist-info")
                        or file.name in {"direct_url.json", "RECORD"}
                    ):
                        continue
                    archive.write(
                        distribution.locate_file(file),
                        root + "runtime/python/Lib/site-packages/" + file.as_posix(),
                    )
        with zipfile.ZipFile(pending) as archive:
            if len(archive.namelist()) != len(set(archive.namelist())):
                raise ValueError("Duplicate archive entry")
            if archive.testzip() is not None:
                raise ValueError("Archive CRC failed")
            if archive.read(root + "LICENSE") != (repo / "LICENSE").read_bytes():
                raise ValueError("License changed")
        pending.replace(target)
        print("CRC verified", target.name, flush=True)
    records = [
        {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
        for path, _ in packages
    ]
    (args.output / "SOURCE-SHA256SUMS.txt").write_text(
        "".join(item["sha256"] + "  " + item["file"] + "\n" for item in records), encoding="utf-8"
    )
    print(json.dumps(records), flush=True)


if __name__ == "__main__":
    main()
