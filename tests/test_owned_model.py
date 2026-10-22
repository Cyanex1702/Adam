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


def test_owned_load_unload_uses_fixed_arguments_and_stops_only_owned_handle(tmp_path, monkeypatch):
    item = installed(tmp_path, monkeypatch)
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
    provider = OwnedLlamaProvider(item)

    async def health():
        return ModelHealth(status="HEALTHY", model_id=item.model.model_id)

    monkeypatch.setattr(provider, "health_check", health)

    async def scenario():
        assert (await provider.load()).status == "HEALTHY"
        handle = provider.process
        assert calls[0][0] == str(tmp_path / "runtime/llama/llama-server.exe")
        assert "--no-agent" in calls[0] and "none" in calls[0]
        await provider.unload()
        assert handle.stopped and provider.process is None
        await provider.unload()

    asyncio.run(scenario())


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
