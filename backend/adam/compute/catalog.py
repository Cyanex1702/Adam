import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from adam.compute.contracts import ComputeError
from adam.core.config import ModelConfig
from adam.core.contracts import Contract, new_id
from adam.core.privacy import contains_secret
from adam.resilience.archive import no_link, scoped
from adam.security.request import check_authority


def config_digest(model: ModelConfig) -> str:
    return hashlib.sha256(model.model_dump_json().encode()).hexdigest()


class ModelProfile(Contract):
    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")
    model: ModelConfig
    managed: bool = False
    model_file: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,140}\.gguf$"
    )
    device: Literal["cpu", "vulkan"] = "cpu"
    source_path: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def valid(self) -> "ModelProfile":
        if self.managed and self.model.context_limit > 32768:
            raise ValueError("MODEL.MANAGED_CONTEXT_LIMIT")
        if self.managed and not self.model_file:
            raise ValueError("MODEL.ARTIFACT_REQUIRED")
        if self.source_path:
            path = Path(self.source_path)
            if (
                not self.managed
                or not path.is_absolute()
                or path.suffix.lower() != ".gguf"
                or ".." in path.parts
                or str(path).startswith(("\\\\", "//"))
                or any(ord(c) < 32 for c in str(path))
            ):
                raise ValueError("MODEL.LOCAL_PATH_INVALID")
        if contains_secret(self.model_dump_json()):
            raise ValueError("MODEL.PROFILE_CREDENTIAL_DENIED")
        return self


class Catalog(Contract):
    format: Literal[1] = 1
    profiles: dict[str, ModelProfile] = Field(default_factory=dict)
    default_id: str = "current"
    previous_id: str | None = None
    reports: dict[str, dict[str, str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self) -> "Catalog":
        if len(self.profiles) > 20 or len(self.reports) > 80:
            raise ValueError("MODEL.CATALOG_LIMIT")
        if self.default_id not in self.profiles:
            raise ValueError("MODEL.CATALOG_INVALID")
        if self.previous_id and self.previous_id not in self.profiles:
            raise ValueError("MODEL.CATALOG_INVALID")
        if any(key != value.profile_id for key, value in self.profiles.items()):
            raise ValueError("MODEL.CATALOG_INVALID")
        return self


def read_catalog(path: Path) -> Catalog:
    no_link(path)
    if path.stat().st_size > 1024**2:
        raise ComputeError("MODEL.CATALOG_INVALID")
    try:
        return Catalog.model_validate_json(path.read_bytes())
    except (ValueError, OSError):
        raise ComputeError("MODEL.CATALOG_INVALID") from None


def publish(root: Path, relative: str, value: Contract | dict[str, object]) -> None:
    path = scoped(root, relative)
    data = value.model_dump(mode="json") if isinstance(value, Contract) else value
    encoded = json.dumps(data, ensure_ascii=False, indent=2).encode()
    if len(encoded) > 1024**2 or contains_secret(encoded.decode()):
        raise ComputeError("MODEL.METADATA_INVALID")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + new_id())
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        check_authority()
        os.replace(temporary, path)
    except OSError:
        raise ComputeError("MODEL.METADATA_IO_FAILED") from None
    finally:
        temporary.unlink(missing_ok=True)
