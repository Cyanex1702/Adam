"""Stdlib-only startup check, usable before ADAM dependencies are installed."""

import importlib
import importlib.metadata
import importlib.util
import os
import sys
import tomllib
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    problems = []
    for line in (root / "requirements.lock.txt").read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, expected = line.split("==", 1)
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = "missing"
        if actual != expected:
            problems.append(f"{name}: {actual} (requires {expected})")
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    try:
        if importlib.metadata.version("adam-runtime") != version:
            problems.append("ADAM package version needs updating")
    except importlib.metadata.PackageNotFoundError:
        problems.append("ADAM editable package is missing")
    spec = importlib.util.find_spec("adam")
    expected_source = root / "backend" / "adam" / "__init__.py"
    if (
        not spec
        or not spec.origin
        or (
            os.path.normcase(os.path.realpath(spec.origin))
            != os.path.normcase(os.path.realpath(expected_source))
        )
    ):
        problems.append("ADAM editable package must point to this project")
    if not problems:
        for module in [
            "fastapi",
            "uvicorn",
            "httpx",
            "pydantic",
            "yaml",
            "pypdf",
            "qdrant_client",
            "onnxruntime",
            "tokenizers",
            "numpy",
            "cryptography",
            "psutil",
            "jsonschema",
            "PIL",
        ]:
            try:
                importlib.import_module(module)
            except Exception:
                problems.append(f"{module}: import failed")
    if problems:
        print("ADAM environment needs repair: " + "; ".join(problems[:6]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
