import json

import pytest
from adam.compute import hardware


@pytest.mark.skipif(hardware.os.name != "nt", reason="Windows Store asset layout")
def test_normal_desktop_reuses_complete_public_store_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cached = tmp_path / "Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/ADAM"
    for relative in ["runtime/llama/llama-server.exe", "models/qwen3-4b-instruct.gguf"]:
        path = cached / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic public asset")
        if relative.endswith(".exe"):
            assert hardware.assets_root() == tmp_path / "ADAM"
    assert hardware.assets_root() == cached
    assert not (tmp_path / "ADAM/runtime.sqlite3").exists()


@pytest.mark.skipif(hardware.os.name != "nt", reason="Windows Store asset layout")
def test_complete_primary_assets_win_over_store_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    primary = tmp_path / "ADAM"
    cached = tmp_path / "Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/ADAM"
    for root in [primary, cached]:
        for relative in ["runtime/llama/llama-server.exe", "models/qwen3-4b-instruct.gguf"]:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic public asset")
    assert hardware.assets_root() == primary


def test_profile_is_offline_private_and_does_not_initialize_store(tmp_path, monkeypatch):
    monkeypatch.setattr(hardware, "gpus", lambda: [])
    root = tmp_path / "not-created"
    result = hardware.profile(root, benchmark=True)
    assert result["network"]["internet_reachability"] == "NOT_PROBED"
    assert result["cpu"]["logical_cores"] >= 1
    assert result["ram_total_bytes"] > 0
    assert result["basic_benchmark"]["mib_per_second"] > 0
    assert not root.exists()
    assert all(key not in result for key in ["hostname", "serial", "ip", "mac"])
    assert "GPU, storage or model quality" in result["basic_benchmark"]["note"]


def test_gpu_parser_supports_8gib_and_unknown_sensors(monkeypatch):
    monkeypatch.setattr(hardware.shutil, "which", lambda _: "synthetic-nvidia-smi")
    monkeypatch.setattr(
        hardware, "command", lambda *args, **kwargs: "Quadro M4000, 8192, 900, 17, N/A\n"
    )
    result = hardware.gpus()[0]
    assert result["vram_total_bytes"] == 8 * 1024**3
    assert result["temperature_c"] is None
    assert result["utilization_percent"] == 17


@pytest.mark.parametrize("value", ["N/A", "NaN", "inf", "-1", "unknown"])
def test_unknown_gpu_numbers_never_become_zero_or_infinite(value):
    assert hardware.number(value) is None


def test_optional_probes_fail_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(hardware, "gpus", lambda: [])
    monkeypatch.setattr(hardware.psutil, "virtual_memory", lambda: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(
        hardware.psutil, "sensors_battery", lambda: (_ for _ in ()).throw(OSError())
    )
    result = hardware.telemetry(tmp_path)
    assert result["ram_available_bytes"] is None and result["battery"] is None
    assert json.dumps(result)


def test_probe_timeout_is_bounded_and_sanitized(monkeypatch):
    monkeypatch.setattr(
        hardware.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("private path")),
    )
    assert hardware.command(["not-a-real-command"]) == ""
