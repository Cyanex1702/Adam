import asyncio
import socket

import pytest
from adam.compute.catalog import ModelProfile
from adam.compute.contracts import ComputeError
from adam.compute.owned import OwnedLlamaProvider, artifact_digest
from adam.core.config import ModelConfig
from adam.models.base import ModelHealth


def installed(tmp_path, monkeypatch):
    (tmp_path / "models").mkdir()
    (tmp_path / "models/fixture.gguf").write_bytes(b"GGUFsynthetic-fixture-weights")
    (tmp_path / "runtime/llama").mkdir(parents=True)
    (tmp_path / "runtime/llama/llama-server.exe").write_bytes(b"synthetic non-executable fixture")
    monkeypatch.setattr("adam.compute.owned.assets_root", lambda: tmp_path)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return ModelProfile(
        profile_id="fixture",
        model=ModelConfig(base_url=f"http://127.0.0.1:{port}"),
        managed=True,
        model_file="fixture.gguf",
    )


@pytest.mark.parametrize("stop_loading", [False, True])
@pytest.mark.parametrize("device", ["cpu", "vulkan"])
def test_owned_load_unload_uses_fixed_arguments_and_stops_only_owned_handle(
    tmp_path, monkeypatch, stop_loading, device
):
    item = installed(tmp_path, monkeypatch)
    item.device = device
    monkeypatch.setattr(
        "adam.compute.owned.command", lambda *args: "Vulkan0: Fixture GPU (8192 MiB)"
    )
    monkeypatch.setattr(
        "adam.compute.owned.gpus",
        lambda: [
            {
                "name": "Fixture GPU",
                "vram_total_bytes": 8 * 1024**3,
                "vram_used_bytes": 0,
            }
        ],
    )
    calls = []

    class Process:
        stopped = False

        def __init__(self, arguments, **kwargs):
            calls.append(arguments)
            assert "shell" not in kwargs

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

    monkeypatch.setattr("adam.compute.owned.subprocess.Popen", Process)
    monkeypatch.setattr(
        "adam.compute.owned.ChildGuard",
        lambda process: type("Guard", (), {"close": lambda self: None})(),
    )
    monkeypatch.setattr("adam.compute.owned.ModelIndicator.start", lambda self: False)
    provider = OwnedLlamaProvider(item)

    async def health():
        if stop_loading:
            await provider.unload()
        return ModelHealth(status="HEALTHY", model_id=item.model.model_id)

    monkeypatch.setattr(provider, "health_check", health)

    async def scenario():
        if stop_loading:
            with pytest.raises(ComputeError, match="MODEL.LOAD_FAILED"):
                await provider.load()
            assert provider.process is None
            return
        assert (await provider.load()).status == "HEALTHY"
        handle = provider.process
        assert calls[0][0] == str(tmp_path / "runtime/llama/llama-server.exe")
        assert "--no-agent" in calls[0]
        assert calls[0][calls[0].index("--device") + 1] == (
            "none" if device == "cpu" else "Vulkan0"
        )
        assert calls[0][calls[0].index("-ngl") + 1] == ("0" if device == "cpu" else "99")
        assert ("--no-repack" in calls[0]) == (device == "cpu")
        assert ("--load-mode" in calls[0]) == (device == "vulkan")
        if device == "vulkan":
            assert calls[0][calls[0].index("--load-mode") + 1] == "none"
        assert calls[0][calls[0].index("--batch-size") + 1] == "64"
        assert calls[0][calls[0].index("--ubatch-size") + 1] == "32"
        await provider.unload()
        assert handle.stopped and provider.process is None
        await provider.unload()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "listing,total,used,code",
    [
        ("", 8 * 1024**3, 0, "MODEL.GPU_UNAVAILABLE"),
        ("Vulkan0: Different GPU (8192 MiB)", 8 * 1024**3, 0, "RESOURCE.GPU_TELEMETRY_UNAVAILABLE"),
        ("Vulkan0: Fixture GPU (8192 MiB)", 8 * 1024**3, 8 * 1024**3, "RESOURCE.VRAM_BUDGET"),
        ("Vulkan0: Fixture GPU (8192 MiB)", None, None, "RESOURCE.GPU_TELEMETRY_UNAVAILABLE"),
    ],
)
def test_gpu_load_rejects_missing_mismatched_or_full_adapter(
    tmp_path, monkeypatch, listing, total, used, code
):
    item = installed(tmp_path, monkeypatch)
    item.device = "vulkan"
    monkeypatch.setattr("adam.compute.owned.command", lambda *args: listing)
    monkeypatch.setattr(
        "adam.compute.owned.gpus",
        lambda: [
            {
                "name": "Fixture GPU",
                "vram_total_bytes": total,
                "vram_used_bytes": used,
            }
        ],
    )
    provider = OwnedLlamaProvider(item)
    with pytest.raises(ComputeError, match=code):
        asyncio.run(provider.load())
    assert provider.process is None


def test_owned_model_refuses_port_collision_without_touching_external_listener(
    tmp_path, monkeypatch
):
    item = installed(tmp_path, monkeypatch)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        item.model.base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        provider = OwnedLlamaProvider(item)
        with pytest.raises(ComputeError, match="PORT_BUSY"):
            asyncio.run(provider.load())
        assert listener.fileno() != -1 and provider.process is None


def test_artifact_digest_detects_changed_or_missing_gguf(tmp_path, monkeypatch):
    item = installed(tmp_path, monkeypatch)
    initial = artifact_digest(item)
    path = tmp_path / "models/fixture.gguf"
    path.write_bytes(b"GGUFdifferent-synthetic-weights")
    assert artifact_digest(item) != initial
    path.write_bytes(b"not-a-gguf")
    with pytest.raises(ComputeError, match="ARTIFACT_INVALID"):
        artifact_digest(item)
    path.unlink()
    with pytest.raises(ComputeError, match="NOT_INSTALLED"):
        artifact_digest(item)


def test_owned_launch_failure_is_sanitized(tmp_path, monkeypatch):
    item = installed(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "adam.compute.owned.subprocess.Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("private path")),
    )
    provider = OwnedLlamaProvider(item)
    with pytest.raises(ComputeError, match="MODEL.LOAD_FAILED"):
        asyncio.run(provider.load())
    assert provider.process is None


@pytest.mark.parametrize("available,repack", [(1300 * 1024**2, False), (4 * 1024**3, True)])
def test_priority_repacking_requires_room_for_an_extra_weight_layout(
    tmp_path, monkeypatch, available, repack
):
    item = installed(tmp_path, monkeypatch)
    calls = []

    class Process:
        stopped = False

        def __init__(self, arguments, **kwargs):
            calls.append(arguments)

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(
        "adam.compute.owned.psutil.virtual_memory",
        lambda: type("Memory", (), {"available": available})(),
    )
    monkeypatch.setattr("adam.compute.owned.subprocess.Popen", Process)
    monkeypatch.setattr(
        "adam.compute.owned.ChildGuard",
        lambda process: type("Guard", (), {"close": lambda self: None})(),
    )
    monkeypatch.setattr("adam.compute.owned.ModelIndicator.start", lambda self: False)
    provider = OwnedLlamaProvider(item, mode="priority")

    async def health():
        return ModelHealth(status="HEALTHY", model_id=item.model.model_id)

    monkeypatch.setattr(provider, "health_check", health)

    async def scenario():
        await provider.load()
        assert provider.repack == repack
        assert ("--no-repack" not in calls[0]) == repack
        await provider.unload()

    asyncio.run(scenario())


@pytest.mark.parametrize("hung_health", [False, True])
def test_elapsed_load_deadline_cleans_owned_process_even_when_health_hangs(
    tmp_path, monkeypatch, hung_health
):
    item = installed(tmp_path, monkeypatch)

    class Process:
        stopped = False

        def __init__(self, *args, **kwargs):
            pass

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

    monkeypatch.setattr("adam.compute.owned.subprocess.Popen", Process)
    monkeypatch.setattr("adam.compute.owned.LOAD_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr("adam.compute.owned.ModelIndicator.start", lambda self: False)
    monkeypatch.setattr(
        "adam.compute.owned.ChildGuard",
        lambda process: type("Guard", (), {"close": lambda self: None})(),
    )
    provider = OwnedLlamaProvider(item)
    handles = []

    async def health():
        handles.append(provider.process)
        if hung_health:
            await asyncio.Event().wait()
        return ModelHealth(status="DEGRADED", model_id=item.model.model_id)

    monkeypatch.setattr(provider, "health_check", health)

    async def scenario():
        with pytest.raises(ComputeError, match="MODEL.LOAD_TIMEOUT"):
            await asyncio.wait_for(provider.load(), timeout=1)
        assert provider.process is None and provider.guard is None
        assert handles and handles[0].stopped

    asyncio.run(scenario())
