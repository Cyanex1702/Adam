from typing import Literal

from pydantic import Field

from adam.core.contracts import Contract

Generation = Literal["daily", "weekly", "monthly", "milestone"]


class BackupConfig(Contract):
    daily: int = Field(default=7, ge=1, le=100)
    weekly: int = Field(default=4, ge=1, le=100)
    monthly: int = Field(default=3, ge=1, le=100)
    milestone: int = Field(default=10, ge=1, le=100)
    max_bytes: int = Field(default=256 * 1024 * 1024, ge=1048576, le=256 * 1024 * 1024)


class BackupError(ValueError):
    def __init__(self, code: str = "BACKUP.INVALID") -> None:
        self.code = code
        super().__init__(code)


class Entry(Contract):
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(ge=0, le=256 * 1024 * 1024)


class Manifest(Contract):
    format: Literal[1] = 1
    release: str
    created_at: str
    generation: Generation
    identity_digest: str
    vault_included: bool
    files: dict[str, Entry]
    schemas: dict[str, int]
    directories: list[str] = Field(default_factory=list, max_length=10000)


class Receipt(Contract):
    backup_id: str
    generation: Generation
    created_at: str
    size_bytes: int
    status: Literal["VERIFIED"] = "VERIFIED"
    vault_included: bool
