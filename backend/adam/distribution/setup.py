"""Pinned opt-in model setup. No shell, arbitrary URLs, or automatic model start."""

import os
import shutil
import threading
import time
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx
import psutil  # type: ignore[import-untyped]

from adam.compute.catalog import Catalog, ModelProfile, publish
from adam.compute.hardware import assets_root
from adam.compute.hardware import profile as hardware
from adam.core.config import ModelConfig, Settings
from adam.distribution.portable import DistributionError
from adam.distribution.releases import safe, sha
from adam.resilience.archive import scoped
from adam.security.request import check_authority

# Exact existing reviewed revisions; no latest-version lookup.
PRESETS = {
    "qwen3-4b-instruct": (
        "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/a06e946bb6b655725eafa393f4a9745d460374c9/",
        "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597",
    ),
    "qwen3-4b-abliterated": (
        "https://huggingface.co/IamLucif3r/Qwen3-4B-Instruct-2507-Abliterated/resolve/c3248878a96c4b72cb4d2eb79069389c5827dbb9/",
        "d416c35bfba822e0156cc5257d4f8cee49f9c83e4a947f86b91d97ee8b98893c",
    ),
}
FILES = {
    "qwen3-4b-instruct": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
    "qwen3-4b-abliterated": "Qwen3-4B-Instruct-2507-Abliterated-Q4_K_M.gguf",
}
RUNTIME = (
    "https://github.com/ggml-org/llama.cpp/releases/download/b11146/llama-b11146-bin-win-vulkan-x64.zip",
    "55a378aa095b466979d85075234f66d7655c7a7483222af0c006c0e55b4d7bd6",
)


class Setup:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.progress: dict[str, Any] = {"status": "IDLE", "bytes": 0}

    def report(self) -> dict[str, Any]:
        observed = hardware(self.settings.data_dir)
        ram = observed["ram_total_bytes"]
        return {
            "hardware": observed,
            "data_dir": str(self.settings.data_dir),
            "prerequisites": {
                "platform": os.name == "nt",
                "bundled_python": True,
                "disk_free_bytes": shutil.disk_usage(self.settings.data_dir).free,
            },
            "recommendation": "CPU Q4 4B, 3 threads, 2048 context; GPU optional"
            if ram >= 8 * 1024**3
            else (
                "Reduced mode: use a separately configured smaller local model; "
                "no automatic 4B download"
            ),
            "presets": list(PRESETS),
            "progress": dict(self.progress),
            "notes": (
                "No quality/safety guarantee; the abliterated preset may produce "
                "unsafe or inaccurate content."
            ),
        }

    def guard(self) -> None:
        check_authority()
        if self.cancel.is_set():
            raise DistributionError("SETUP.CANCELLED")

    def download(self, url: str, target: Path, expected: str, limit: int) -> None:
        self.guard()
        if target.is_file() and sha(target) == expected:
            return
        part = target.with_suffix(target.suffix + ".part")
        target.parent.mkdir(parents=True, exist_ok=True)
        from adam.resilience.archive import no_link

        no_link(target)
        no_link(part)
        try:
            # HTTPS host-changing redirects are necessary for HF/GitHub CDN objects;
            # URLs are pinned constants, never accepted from a request or model.
            with (
                httpx.Client(timeout=30, trust_env=False, follow_redirects=True) as client,
                client.stream("GET", url) as response,
            ):
                response.raise_for_status()
                total = 0
                deadline = time.monotonic() + 7200
                with part.open("wb") as stream:
                    for chunk in response.iter_bytes(1024**2):
                        self.guard()
                        total += len(chunk)
                        if total > limit or time.monotonic() > deadline:
                            raise DistributionError("SETUP.DOWNLOAD_LIMIT")
                        stream.write(chunk)
                        self.progress.update(bytes=total)
            if sha(part) != expected:
                raise DistributionError("SETUP.CHECKSUM_FAILED")
            self.guard()
            os.replace(part, target)
        finally:
            part.unlink(missing_ok=True)

    def install(self, model_id: str) -> dict[str, Any]:
        if model_id not in PRESETS or not self.lock.acquire(blocking=False):
            raise DistributionError("SETUP.BUSY_OR_UNKNOWN")
        try:
            self.guard()
            if psutil.virtual_memory().total < 8 * 1024**3:
                raise DistributionError("SETUP.HARDWARE_REDUCED_MODE")
            root = assets_root()
            if shutil.disk_usage(root).free < 4 * 1024**3:
                raise DistributionError("SETUP.DISK_SPACE")
            self.progress = {"status": "DOWNLOADING_MODEL", "bytes": 0}
            base, expected = PRESETS[model_id]
            self.download(
                base + FILES[model_id],
                scoped(root, "models/" + model_id + ".gguf"),
                expected,
                3 * 1024**3,
            )
            self.progress.update(status="DOWNLOADING_RUNTIME", bytes=0)
            archive = scoped(root, "runtime/llama-vulkan.zip")
            self.download(RUNTIME[0], archive, RUNTIME[1], 256 * 1024**2)
            target = scoped(root, "runtime/llama")
            receipt = scoped(root, "runtime/installed-sha256.txt")
            if (
                not (target / "llama-server.exe").is_file()
                or not receipt.is_file()
                or receipt.read_text().strip() != RUNTIME[1]
            ):
                for process in psutil.process_iter(["name", "exe"]):
                    if (
                        process.info["name"] == "llama-server.exe"
                        and process.info["exe"]
                        and Path(process.info["exe"]).resolve()
                        == (target / "llama-server.exe").resolve()
                    ):
                        raise DistributionError("SETUP.RUNTIME_BUSY")
                with TemporaryDirectory(prefix="llama-", dir=archive.parent) as temporary:
                    stage = Path(temporary)
                    with zipfile.ZipFile(archive) as source:
                        if sum(i.file_size for i in source.infolist()) > 1024**3:
                            raise DistributionError("SETUP.DOWNLOAD_LIMIT")
                        for info in source.infolist():
                            if info.is_dir():
                                continue
                            if not safe(info.filename):
                                raise DistributionError("SETUP.PATH_DENIED")
                            destination = scoped(stage, info.filename)
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            with source.open(info) as src, destination.open("xb") as dst:
                                shutil.copyfileobj(src, dst)
                    if not (stage / "llama-server.exe").is_file():
                        raise DistributionError("SETUP.RUNTIME_INVALID")
                    if target.exists():
                        target.rename(target.with_name("llama-previous-" + str(time.time_ns())))
                    stage.rename(target)
                    receipt.write_text(RUNTIME[1], encoding="utf-8")
            self.guard()
            model = ModelConfig(
                model_id=model_id,
                display_name="Qwen3 4B (CPU setup)",
                context_limit=2048,
                max_tokens=512,
            )
            catalog = Catalog(
                profiles={
                    "current": ModelProfile(
                        profile_id="current",
                        model=model,
                        managed=True,
                        model_file=model_id + ".gguf",
                        device="cpu",
                    )
                }
            )
            publish(self.settings.data_dir, "config/model-catalog.json", catalog)
            self.progress.update(status="VERIFIED_RESTART_REQUIRED")
            return dict(self.progress)
        except DistributionError:
            self.progress.update(status="FAILED_OR_CANCELLED")
            raise
        except (httpx.HTTPError, OSError, zipfile.BadZipFile):
            self.progress.update(status="FAILED")
            raise DistributionError("SETUP.DOWNLOAD_OR_IO_FAILED") from None
        finally:
            self.lock.release()
