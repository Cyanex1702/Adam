import asyncio
import hashlib
import os
import socket
import subprocess
from urllib.parse import urlparse

from adam.compute.catalog import ModelProfile
from adam.compute.contracts import ComputeError
from adam.compute.hardware import assets_root, gpus
from adam.core.config import ModelConfig
from adam.models.base import ModelHealth
from adam.models.llama_cpp import LlamaCppProvider
from adam.resilience.archive import scoped


def artifact_digest(profile: ModelProfile) -> str | None:
    if not profile.managed:
        return None
    path = scoped(assets_root(), "models/" + str(profile.model_file))
    try:
        if not path.is_file() or path.stat().st_size < 8:
            raise ComputeError("MODEL.NOT_INSTALLED")
        before = path.stat()
        with path.open("rb") as stream:
            if stream.read(4) != b"GGUF":
                raise ComputeError("MODEL.ARTIFACT_INVALID")
            stream.seek(0)
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ComputeError("MODEL.ARTIFACT_CHANGED")
        return digest
    except OSError:
        raise ComputeError("MODEL.NOT_INSTALLED") from None


class OwnedLlamaProvider(LlamaCppProvider):
    """Only an installed ADAM executable and allowlisted GGUF basename; no shell."""

    def __init__(self, profile: ModelProfile) -> None:
        super().__init__(profile.model)
        self.profile = profile
        self.process: subprocess.Popen[bytes] | None = None

    async def load(self) -> ModelHealth:
        if self.process and self.process.poll() is None:
            return await self.health_check()
        parsed = urlparse(self.config.base_url)
        port = parsed.port or 80
        if parsed.hostname != "127.0.0.1" or not 1024 <= port <= 65535:
            raise ComputeError("MODEL.MANAGED_ORIGIN_INVALID")
        with socket.socket() as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise ComputeError("MODEL.PORT_BUSY")
        root = assets_root()
        executable = scoped(root, "runtime/llama/llama-server.exe")
        weights = scoped(root, "models/" + str(self.profile.model_file))
        if not executable.is_file() or not weights.is_file():
            raise ComputeError("MODEL.NOT_INSTALLED")
        with weights.open("rb") as stream:
            if stream.read(4) != b"GGUF":
                raise ComputeError("MODEL.ARTIFACT_INVALID")
        if self.profile.device == "vulkan":
            devices = gpus()
            device = devices[0] if devices else {}
            if device.get("vram_total_bytes") is None or device.get("vram_used_bytes") is None:
                raise ComputeError("RESOURCE.GPU_TELEMETRY_UNAVAILABLE")
            if (
                device["vram_total_bytes"] - device["vram_used_bytes"]
                < weights.stat().st_size + 256 * 1024**2
            ):
                raise ComputeError("RESOURCE.VRAM_BUDGET")
        arguments = [
            str(executable),
            "-m",
            str(weights),
            "--alias",
            self.config.model_id,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "-c",
            str(self.config.context_limit),
            "-t",
            "3",
            "--threads-batch",
            "3",
            "--parallel",
            "1",
            "--jinja",
            "--reasoning-budget",
            "0",
            "--no-webui",
            "--no-agent",
            "--no-slots",
            "--log-disable",
            "--poll",
            "0",
            "--poll-batch",
            "0",
            "--device",
            "none" if self.profile.device == "cpu" else "Vulkan0",
            "-ngl",
            "0" if self.profile.device == "cpu" else "99",
        ]
        ready = False
        try:
            self.process = subprocess.Popen(
                arguments,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            for _ in range(120):
                if self.process.poll() is not None:
                    raise ComputeError("MODEL.LOAD_FAILED")
                health = await self.health_check()
                if health.status == "HEALTHY":
                    ready = True
                    return health
                await asyncio.sleep(0.5)
            raise ComputeError("MODEL.LOAD_TIMEOUT")
        except OSError:
            raise ComputeError("MODEL.LOAD_FAILED") from None
        finally:
            if not ready:
                await self.unload()

    async def unload(self) -> None:
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 10)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 10)


def external(model: ModelConfig) -> LlamaCppProvider:
    return LlamaCppProvider(model)
