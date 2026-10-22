import csv
import hashlib
import io
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil  # type: ignore[import-untyped]

from adam.core.contracts import utc_now


def assets_root() -> Path:
    explicit = os.environ.get("ADAM_ASSETS_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    primary = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "ADAM"
    if os.name == "nt":
        cached = primary.parent / "Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/ADAM"
        # Windows Store filesystem virtualization resolves existing public assets
        # individually, even when the parent ADAM directory resolves to the host view.
        # Accept only this known public cache, never redirect personal runtime data.
        for relative in ["runtime/llama/llama-server.exe", "models/qwen3-4b-instruct.gguf"]:
            path = primary / relative
            if path.is_file() and path.resolve() == (cached / relative).resolve():
                return cached
        # A normal Start-menu launch has no Store virtualization. Public assets
        # installed through Codex can still live in its known cache. Reuse that
        # complete asset pair without changing the personal data directory.
        required = ["runtime/llama/llama-server.exe", "models/qwen3-4b-instruct.gguf"]
        if not (primary / "runtime/llama/llama-server.exe").is_file() and all(
            (cached / name).is_file() for name in required
        ):
            return cached
    return primary


def command(arguments: list[str], timeout: float = 3) -> str:
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.stdout[:65536]
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return ""


def cpu_name() -> str:
    if os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            ) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or "UNKNOWN"


def number(value: str) -> float | None:
    try:
        result = float(value.strip())
        return result if 0 <= result < 10**12 else None
    except ValueError:
        return None


def gpus() -> list[dict[str, Any]]:
    executable = shutil.which("nvidia-smi")
    if not executable and os.name == "nt":
        candidate = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32/nvidia-smi.exe"
        if candidate.is_file():
            executable = str(candidate)
    if executable:
        output = command(
            [
                executable,
                "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ]
        )
        detected = []
        for row in csv.reader(io.StringIO(output)):
            if len(row) != 5:
                continue
            total, used, utilization, temperature = map(number, row[1:])
            detected.append(
                {
                    "name": row[0].strip(),
                    "vram_total_bytes": int(total * 1024**2) if total is not None else None,
                    "vram_used_bytes": int(used * 1024**2) if used is not None else None,
                    "utilization_percent": utilization,
                    "temperature_c": temperature,
                    "source": "nvidia-smi",
                }
            )
        if detected:
            return detected
    # AdapterRAM is a 32-bit CIM field and cannot represent an 8 GiB GPU reliably.
    # Fall back to names only, never report a truncated VRAM figure as measured.
    if os.name == "nt":
        powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / (
            "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        output = command(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ],
            timeout=6,
        )
        return [
            {
                "name": name.strip(),
                "vram_total_bytes": None,
                "vram_used_bytes": None,
                "utilization_percent": None,
                "temperature_c": None,
                "source": "CIM-name-only",
            }
            for name in output.splitlines()
            if name.strip()
        ]
    return []


def existing_parent(path: Path) -> Path:
    selected = path.resolve()
    while not selected.exists() and selected != selected.parent:
        selected = selected.parent
    return selected


def telemetry(data_dir: Path, *, gpu: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sampled_at": utc_now().isoformat(),
        "ram_total_bytes": None,
        "ram_available_bytes": None,
        "ram_used_percent": None,
        "process_ram_bytes": None,
        "cpu_percent": None,
        "cpu_sample": "previous interval; first sample unavailable",
        "disk_free_bytes": None,
        "disk_total_bytes": None,
        "gpus": [],
        "battery": None,
        "cpu_temperatures_c": None,
    }
    try:
        memory = psutil.virtual_memory()
        result.update(
            ram_total_bytes=int(memory.total),
            ram_available_bytes=int(memory.available),
            ram_used_percent=float(memory.percent),
        )
        result["process_ram_bytes"] = int(psutil.Process().memory_info().rss)
        # A brief, bounded interval avoids psutil's meaningless first nonblocking zero.
        result["cpu_percent"] = float(psutil.cpu_percent(interval=0.05))
        result["cpu_sample"] = "system utilization over 50 ms"
    except (psutil.Error, OSError, ValueError):
        pass
    try:
        disk = shutil.disk_usage(existing_parent(data_dir))
        result.update(disk_free_bytes=disk.free, disk_total_bytes=disk.total)
    except OSError:
        pass
    try:
        battery = psutil.sensors_battery()
        if battery:
            result["battery"] = {
                "percent": float(battery.percent),
                "plugged": battery.power_plugged,
            }
        temperatures: dict[str, Any] = getattr(psutil, "sensors_temperatures", lambda: {})()
        values = [float(sensor.current) for group in temperatures.values() for sensor in group]
        result["cpu_temperatures_c"] = values or None
    except (psutil.Error, OSError, ValueError, NotImplementedError):
        pass
    if gpu:
        result["gpus"] = gpus()
    return result


def profile(data_dir: Path, *, benchmark: bool = False) -> dict[str, Any]:
    sample = telemetry(data_dir)
    interfaces = None
    try:
        interfaces = any(
            item.isup
            for name, item in psutil.net_if_stats().items()
            if "loopback" not in name.casefold() and name != "lo"
        )
    except (psutil.Error, OSError):
        pass
    root = assets_root()
    result: dict[str, Any] = {
        "observed_at": sample["sampled_at"],
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "cpu": {
            "name": cpu_name(),
            "logical_cores": os.cpu_count(),
            "physical_cores": psutil.cpu_count(logical=False),
        },
        "ram_total_bytes": sample["ram_total_bytes"],
        "gpus": sample["gpus"],
        "storage": {
            "total_bytes": sample["disk_total_bytes"],
            "free_bytes": sample["disk_free_bytes"],
            "scope": "volume containing data directory",
        },
        "runtime": {
            "python": platform.python_version(),
            "llama_executable_present": (root / "runtime/llama/llama-server.exe").is_file(),
        },
        "acceleration": {
            "cpu": "AVAILABLE",
            "gpu": "DETECTED_NOT_RUNTIME_VERIFIED" if sample["gpus"] else "UNKNOWN",
        },
        "network": {"non_loopback_interface_up": interfaces, "internet_reachability": "NOT_PROBED"},
        "note": "Offline observation; null means unavailable. "
        "No hostname, serial, MAC or IP collected.",
    }
    if benchmark:
        payload = b"ADAM synthetic local compute benchmark\n" * 30000
        started = time.perf_counter()
        for _ in range(8):
            hashlib.sha256(payload).digest()
        elapsed = time.perf_counter() - started
        result["basic_benchmark"] = {
            "kind": "SHA256_MEMORY_ONLY",
            "bytes": len(payload) * 8,
            "elapsed_ms": elapsed * 1000,
            "mib_per_second": len(payload) * 8 / max(elapsed, 1e-9) / 1024**2,
            "note": "Not an LLM, GPU, storage or model quality score.",
        }
    return result
