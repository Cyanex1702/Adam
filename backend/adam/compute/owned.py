import asyncio
import hashlib
import os
import socket
import subprocess
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import psutil  # type: ignore[import-untyped]

from adam.compute.catalog import ModelProfile
from adam.compute.contracts import ComputeError
from adam.compute.hardware import assets_root, gpus
from adam.compute.indicator import ModelIndicator
from adam.compute.process_guard import ChildGuard
from adam.core.config import ModelConfig
from adam.models.base import ModelHealth
from adam.models.llama_cpp import LlamaCppProvider
from adam.resilience.archive import scoped


def model_path(profile: ModelProfile) -> Path:
    if not profile.source_path:
        return scoped(assets_root(), "models/" + str(profile.model_file))
    from adam.resilience.archive import no_link

    path = Path(profile.source_path)
    for item in [path, *path.parents]:
        no_link(item)
    return path.resolve()


def artifact_digest(profile: ModelProfile) -> str | None:
    if not profile.managed:
        return None
    path = model_path(profile)
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

    def __init__(self, profile: ModelProfile, mode: Literal["eco", "priority"] = "eco") -> None:
        super().__init__(profile.model)
        self.profile = profile
        self.mode = mode
        self.process: subprocess.Popen[bytes] | None = None
        self.guard: ChildGuard | None = None
        self.indicator: ModelIndicator | None = None
        self.repack = False

    async def load(self) -> ModelHealth:
        if self.process and self.process.poll() is None:
            return await self.health_check()
        if self.process is not None:
            await self.unload()
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
        weights = model_path(self.profile)
        if not executable.is_file() or not weights.is_file():
            raise ComputeError("MODEL.NOT_INSTALLED")
        with weights.open("rb") as stream:
            if stream.read(4) != b"GGUF":
                raise ComputeError("MODEL.ARTIFACT_INVALID")
        if self.profile.device == "cpu":
            required = weights.stat().st_size + max(
                1024 * 1024**2, self.config.context_limit * 128 * 1024
            )
            try:
                available = psutil.virtual_memory().available
                if available < required:
                    raise ComputeError("RESOURCE.MODEL_RAM_BUDGET")
                # Repacking can retain both the mapped GGUF and another weight
                # layout. On this 4B CPU model it added about 1.64 GiB of RSS.
                # Eco saves that RAM; Priority opts in only with room for both.
                self.repack = self.mode == "priority" and available >= (
                    required + weights.stat().st_size + 512 * 1024**2
                )
            except (psutil.Error, OSError):
                raise ComputeError("RESOURCE.TELEMETRY_UNAVAILABLE") from None
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
        threads = min(2 if self.mode == "eco" else 6, max(1, (os.cpu_count() or 2) - 1))
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
            str(threads),
            "--threads-batch",
            str(threads),
            "--parallel",
            "1",
            "--batch-size",
            "64" if self.mode == "eco" else "128",
            "--ubatch-size",
            "32" if self.mode == "eco" else "64",
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
        if self.profile.device == "cpu" and not self.repack:
            arguments.append("--no-repack")
        ready = False
        try:
            self.process = subprocess.Popen(
                arguments,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    | (
                        subprocess.BELOW_NORMAL_PRIORITY_CLASS
                        if self.mode == "eco"
                        else subprocess.ABOVE_NORMAL_PRIORITY_CLASS
                    )
                )
                if os.name == "nt"
                else 0,
            )
            self.guard = ChildGuard(self.process)
            loop = asyncio.get_running_loop()

            def stop_model() -> None:
                loop.call_soon_threadsafe(lambda: asyncio.create_task(self.unload()))

            self.indicator = ModelIndicator(
                stop_model,
                self.mode,
            )
            await asyncio.to_thread(self.indicator.start)
            for _ in range(120):
                if self.process is None or self.process.poll() is not None:
                    raise ComputeError("MODEL.LOAD_FAILED")
                health = await self.health_check()
                if self.process is None:
                    raise ComputeError("MODEL.LOAD_FAILED")
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
        guard, self.guard = self.guard, None
        indicator, self.indicator = self.indicator, None
        if indicator:
            await asyncio.to_thread(indicator.close)
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, 10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, 10)
        finally:
            if guard:
                guard.close()


def external(model: ModelConfig) -> LlamaCppProvider:
    return LlamaCppProvider(model)
