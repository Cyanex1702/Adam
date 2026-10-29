"""Refuse a desktop backend that does not contain the checked-out Python source."""

import argparse
import types
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def canonical(code: types.CodeType) -> types.CodeType:
    return code.replace(
        co_filename="",
        co_consts=tuple(
            canonical(value) if isinstance(value, types.CodeType) else value
            for value in code.co_consts
        ),
    )


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service",
        type=Path,
        default=repo / "apps/desktop/src-tauri/resources/backend/adam-service.exe",
    )
    args = parser.parse_args()
    archive = CArchiveReader(str(args.service)).open_embedded_archive("PYZ.pyz")
    mismatches = []
    count = 0
    for source in (repo / "backend/adam").rglob("*.py"):
        parts = list(source.relative_to(repo / "backend").with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = ".".join(parts)
        actual = archive.extract(module)
        expected = compile(source.read_bytes(), str(source), "exec", optimize=0)
        if not isinstance(actual, types.CodeType) or canonical(actual) != canonical(expected):
            mismatches.append(module)
        count += 1
    if not count or mismatches:
        raise SystemExit(
            "Frozen backend differs from source: "
            + ", ".join(mismatches)
            + ". Rebuild without -Incremental before packaging."
        )
    print(f"Verified {count} frozen ADAM modules against source.")


if __name__ == "__main__":
    main()
