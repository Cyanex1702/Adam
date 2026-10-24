from typing import Literal

from pydantic import Field

from adam.core.contracts import Contract


class ComputeConfig(Contract):
    mode: Literal["eco", "priority"] = "eco"
    min_free_ram_mib: int = Field(default=512, ge=64, le=65536)
    min_free_disk_mib: int = Field(default=128, ge=16, le=65536)
    min_free_vram_mib: int = Field(default=256, ge=64, le=65536)
    gpu_admission: bool = False
    ram_pressure_percent: float = Field(default=94, ge=50, le=99.9)
    failure_limit: int = Field(default=2, ge=1, le=10)
    cooldown_seconds: float = Field(default=30, ge=0, le=600)
    queue_limit: int = Field(default=16, ge=1, le=128)
    queue_timeout_seconds: float = Field(default=120, ge=1, le=600)
    benchmark_max_case_ms: float = Field(default=180000, ge=1000, le=600000)


class ComputeError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
