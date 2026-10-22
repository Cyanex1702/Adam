import hashlib
from pathlib import Path

import pytest
from adam.compute.hardware import assets_root
from adam.portable import prepare


def make_bundle(tmp_path, monkeypatch):
    (tmp_path / "models").mkdir()
    (tmp_path / "runtime/llama").mkdir(parents=True)
    raw = b"GGUF-synthetic-unit-test-only"
    (tmp_path / "models/qwen3-4b-instruct.gguf").write_bytes(raw)
    (tmp_path / "runtime/llama/llama-server.exe").write_bytes(b"SYNTHETIC-NOT-EXECUTABLE")
    (tmp_path / "adam.portable.toml").write_text(
        '[model]\nmodel_id="qwen3-4b-instruct"\ncontext_limit=2048\nmax_tokens=384\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(
        __import__("adam.portable", fromlist=["PRESETS"]).PRESETS,
        "qwen3-4b-instruct",
        ("https://example.invalid/", hashlib.sha256(raw).hexdigest()),
    )


def test_explicit_assets_root_is_relocatable_and_does_not_redirect_data(tmp_path, monkeypatch):
    monkeypatch.setenv("ADAM_ASSETS_ROOT", str(tmp_path / "moved assets"))
    assert assets_root() == (tmp_path / "moved assets").resolve()


def test_portable_prepares_cpu_catalog_and_separate_data(tmp_path, monkeypatch):
    make_bundle(tmp_path, monkeypatch)
    monkeypatch.setenv("ADAM_ASSETS_ROOT", str(tmp_path))
    target = tmp_path / "isolated data"
    settings = prepare(tmp_path, target)
    assert settings.data_dir == target.resolve() and settings.model.context_limit == 2048
    assert (target / "config/model-catalog.json").is_file()
    assert settings.knowledge.allowed_roots == [tmp_path / "samples"]
    assert prepare(tmp_path, target).model == settings.model


def test_portable_wrong_hash_and_missing_runtime_fail_closed(tmp_path, monkeypatch):
    make_bundle(tmp_path, monkeypatch)
    monkeypatch.setenv("ADAM_ASSETS_ROOT", str(tmp_path))
    model = tmp_path / "models/qwen3-4b-instruct.gguf"
    model.write_bytes(b"GGUF-corrupted")
    with pytest.raises(ValueError, match="CHECKSUM"):
        prepare(tmp_path, tmp_path / "data")
    model.unlink()
    with pytest.raises(ValueError, match="MISSING"):
        prepare(tmp_path, tmp_path / "data")


def test_bat_uses_relative_bundled_python_and_editable_source():
    root = Path(__file__).parents[1]
    text = (root / "RUN_ADAM.bat").read_text(encoding="utf-8")
    assert "%~dp0runtime" in text and "-m adam.portable" in text
    assert "C:\\Users" not in text
