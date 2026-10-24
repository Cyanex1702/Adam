"""Explicit local GGUF discovery and opt-in, serial model routing."""

import asyncio
import hashlib
import os
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from adam.compute.catalog import ModelProfile, publish
from adam.compute.contracts import ComputeError
from adam.compute.hardware import assets_root
from adam.core.config import ModelConfig
from adam.core.contracts import Contract
from adam.resilience.archive import no_link, scoped
from adam.security.request import check_authority

Role = Literal["quick", "balanced", "reasoning"]


class Entry(Contract):
    id: str = Field(pattern=r"^[a-f0-9]{20}$")
    path: str = Field(max_length=1024)
    bytes: int = Field(ge=8, le=512 * 1024**3)
    modified_ns: int = Field(ge=0)
    role: Role = "balanced"
    approved: bool = False
    profile_id: str | None = None
    sha256: str | None = None

    @field_validator("path")
    @classmethod
    def local_path(cls, value: str) -> str:
        path = Path(value)
        if (
            not path.is_absolute()
            or path.suffix.lower() != ".gguf"
            or ".." in path.parts
            or value.startswith(("\\\\", "//"))
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("MODEL.LOCAL_PATH_INVALID")
        return value


class LibraryState(Contract):
    format: Literal[1] = 1
    automatic: bool = False
    entries: dict[str, Entry] = Field(default_factory=dict, max_length=100)

    @model_validator(mode="after")
    def consistent(self) -> "LibraryState":
        if any(key != entry.id for key, entry in self.entries.items()):
            raise ValueError("MODEL.LIBRARY_INVALID")
        return self


def complexity(text: str) -> Role:
    words = set(text.casefold().split())
    if (
        len(text) > 1200
        or (text.count(".") >= 3 and "?" in text)
        or words.intersection(
            {
                "prove",
                "debug",
                "analyze",
                "analyse",
                "reason",
                "solve",
                "compare",
                "calculate",
                "logic",
                "contradiction",
            }
        )
    ):
        return "reasoning"
    return "quick" if len(text) < 160 else "balanced"


class ModelLibrary:
    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self.manager = controller.manager
        self.root = controller.root
        self.state = LibraryState()
        self.error: str | None = None
        self.last_route: dict[str, Any] | None = None
        self.failed_until: dict[str, float] = {}
        self.lock = asyncio.Lock()
        path = scoped(self.root, "config/model-library.json")
        if path.exists():
            try:
                if path.stat().st_size > 1024**2:
                    raise ValueError
                self.state = LibraryState.model_validate_json(path.read_bytes())
                if len(self.state.entries) > 100:
                    raise ValueError
            except (ValueError, OSError):
                self.state = LibraryState()
                self.error = "MODEL.LIBRARY_INVALID"

    def save(self) -> None:
        if self.error:
            raise ComputeError(self.error)
        publish(self.root, "config/model-library.json", self.state)

    def status(self) -> dict[str, Any]:
        return {
            "automatic": self.state.automatic,
            "entries": [item.model_dump() for item in self.state.entries.values()],
            "error": self.error,
            "last_route": self.last_route,
            "active_profile": self.controller.active_id,
            "scope": (
                "Local GGUF files only. Discovery does not load, copy or approve a "
                "model. Role and size are estimates, not reasoning benchmarks."
            ),
        }

    def scan(self, folder: str | None = None) -> dict[str, Any]:
        if self.error:
            raise ComputeError(self.error)
        home = Path.home()
        roots = (
            [Path(folder)]
            if folder
            else [
                assets_root() / "models",
                home / "Models",
                home / "Downloads",
                home / ".lmstudio/models",
                home / ".cache/huggingface/hub",
            ]
        )
        if any(
            not p.is_absolute() or str(p).startswith(("\\\\", "//")) or ".." in p.parts
            for p in roots
        ):
            raise ComputeError("MODEL.SCAN_LOCAL_FOLDER_REQUIRED")
        deadline, visited, found = time.monotonic() + 5, 0, 0
        pending = [(p, 0) for p in roots]
        while (
            pending
            and visited < 5000
            and time.monotonic() < deadline
            and len(self.state.entries) < 100
        ):
            check_authority()
            directory, depth = pending.pop()
            try:
                for ancestor in [directory, *directory.parents]:
                    no_link(ancestor)
                with os.scandir(directory) as listing:
                    for item in listing:
                        visited += 1
                        if visited >= 5000 or time.monotonic() >= deadline:
                            break
                        path = Path(item.path)
                        if item.is_symlink() or (
                            hasattr(path, "is_junction") and path.is_junction()
                        ):
                            continue
                        if item.is_dir(follow_symlinks=False) and depth < 8:
                            pending.append((path, depth + 1))
                        elif item.is_file(follow_symlinks=False) and path.suffix.lower() == ".gguf":
                            with path.open("rb") as stream:
                                header = stream.read(8)
                            if header[:4] != b"GGUF" or int.from_bytes(
                                header[4:], "little"
                            ) not in {2, 3}:
                                continue
                            stat = path.stat()
                            identifier = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[
                                :20
                            ]
                            old = self.state.entries.get(identifier)
                            if old and (old.bytes, old.modified_ns) == (
                                stat.st_size,
                                stat.st_mtime_ns,
                            ):
                                continue
                            role: Role = "quick" if stat.st_size < 2200 * 1024**2 else "balanced"
                            self.state.entries[identifier] = Entry(
                                id=identifier,
                                path=str(path.resolve()),
                                bytes=stat.st_size,
                                modified_ns=stat.st_mtime_ns,
                                role=role,
                            )
                            found += 1
                            if len(self.state.entries) >= 100:
                                break
            except (OSError, ValueError):
                continue
        self.save()
        return {
            **self.status(),
            "new_or_changed": found,
            "visited": visited,
            "bounded_scan": True,
            "limits": (
                "5 seconds, 5000 directory entries, depth 8, at most 100 models. "
                "Add a specific folder to search elsewhere."
            ),
        }

    def current(self, item: Entry) -> bool:
        try:
            path = Path(item.path)
            for part in [path, *path.parents]:
                no_link(part)
            stat = path.stat()
            return (stat.st_size, stat.st_mtime_ns) == (item.bytes, item.modified_ns)
        except (OSError, ValueError):
            return False

    async def approve(self, identifier: str, role: Role) -> dict[str, Any]:
        item = self.state.entries.get(identifier)
        if not item or not self.current(item):
            raise ComputeError("MODEL.DISCOVERY_CHANGED_RESCAN")
        from adam.compute.owned import artifact_digest

        profile_id = "local-" + identifier
        settings = self.manager.settings
        profile = ModelProfile(
            profile_id=profile_id,
            managed=True,
            source_path=item.path,
            model_file=Path(item.path).name,
            device="cpu",
            model=ModelConfig(
                base_url=settings.model.base_url,
                model_id=profile_id,
                display_name=Path(item.path).stem[:140],
                context_limit=min(settings.model.context_limit, 4096),
                max_tokens=min(settings.model.max_tokens, 768),
                temperature=0.2,
                seed=42,
                timeout_seconds=300,
            ),
        )
        existing = self.controller.catalog.profiles.get(profile_id)
        if existing:
            if existing.source_path != item.path or not existing.managed:
                raise ComputeError("MODEL.PROFILE_EXISTS")
            profile = existing
        digest = await asyncio.to_thread(artifact_digest, profile)
        check_authority()
        if not self.current(item):
            raise ComputeError("MODEL.DISCOVERY_CHANGED_RESCAN")
        if profile_id not in self.controller.catalog.profiles:
            await self.controller.register(profile)
        item.approved, item.profile_id, item.sha256, item.role = True, profile_id, digest, role
        self.save()
        return self.status()

    async def activate(self, identifier: str) -> dict[str, Any]:
        item = self.state.entries.get(identifier)
        if not item or not item.approved or not item.profile_id or not self.current(item):
            raise ComputeError("MODEL.APPROVAL_REQUIRED_OR_CHANGED")
        controller, manager = self.controller, self.manager
        profile = controller.catalog.profiles.get(item.profile_id)
        if not profile or controller.pending_previous:
            raise ComputeError("MODEL.LIFECYCLE_BUSY")
        if controller.active_id == item.profile_id and not manager.detached and not manager.error:
            return {"selected": item.profile_id, "switched": False}
        from adam.compute.owned import artifact_digest

        if await asyncio.to_thread(artifact_digest, profile) != item.sha256 or not self.current(
            item
        ):
            raise ComputeError("MODEL.ARTIFACT_CHANGED")
        check_authority()
        previous_id, previous_model = controller.active_id, manager.settings.model
        previous_retry_at = manager.retry_at
        was_ready = not manager.detached and not manager.error
        with controller.disk_lock():
            async with manager.operation():
                await manager.delegate.unload()
                manager.delegate = controller.factory(profile)
                manager.settings.model = profile.model
                manager.gpu_required = False
                manager.detached, manager.error = True, None
                controller.active_id = item.profile_id
            try:
                check_authority()
                health = await manager.load()
                check_authority()
                if health.status != "HEALTHY":
                    raise ComputeError(health.reason or "MODEL.UNAVAILABLE")
            except (ValueError, OSError) as error:
                await manager.delegate.unload()
                controller.active_id = previous_id
                manager.settings.model = previous_model
                previous = controller.catalog.profiles[previous_id]
                manager.delegate = controller.factory(previous)
                manager.gpu_required = previous.device == "vulkan"
                manager.error, manager.detached = None, True
                # A candidate's failure cooldown must not prevent the one rollback
                # attempt. Restore the prior deadline; ordinary RAM checks still run.
                manager.retry_at = previous_retry_at
                if was_ready:
                    try:
                        await manager.load()
                    except (ValueError, OSError):
                        pass
                raise ComputeError(getattr(error, "code", "MODEL.LOAD_FAILED")) from None
        return {
            "selected": item.profile_id,
            "switched": True,
            "persistence": "Current runtime only; your saved default is unchanged.",
        }

    async def route(self, text: str) -> None:
        async with self.lock:
            await self._route(text)

    async def _route(self, text: str) -> None:
        if (
            not self.state.automatic
            or self.error
            or self.controller.pending_previous
            or self.manager.turns
        ):
            return
        resource = self.manager.observe()
        available = resource.get("ram_available_bytes")
        if not isinstance(available, int):
            return
        # Reclaimable memory is the actual owned process RSS, not total system usage.
        process = getattr(self.manager.delegate, "process", None)
        if process and process.poll() is None:
            import psutil  # type: ignore[import-untyped]

            try:
                available += psutil.Process(process.pid).memory_info().rss
            except psutil.Error:
                pass
        candidates = [
            item
            for item in list(self.state.entries.values())
            if item.approved
            and self.failed_until.get(item.id, 0) <= time.monotonic()
            and item.profile_id in self.controller.catalog.profiles
            and item.bytes + 1024**3 < available
            and self.current(item)
        ]
        if not candidates:
            self.last_route = {
                "reason": (
                    "No approved alternative fits the estimated RAM budget; current "
                    "selection retained."
                )
            }
            return
        role = complexity(text)
        preferred = [item for item in candidates if item.role == role] or candidates
        chosen = (
            min(preferred, key=lambda item: item.bytes)
            if self.manager.config.mode == "eco"
            else max(preferred, key=lambda item: item.bytes)
        )
        check_authority()
        try:
            result = await self.activate(chosen.id)
            self.last_route = {
                **result,
                "task_estimate": role,
                "performance_mode": self.manager.config.mode,
                "reason": (
                    "Approved role/size heuristic within estimated available RAM. This "
                    "is not a quality guarantee."
                ),
            }
        except (ValueError, OSError) as error:
            self.failed_until[chosen.id] = time.monotonic() + 60
            self.last_route = {
                "error": getattr(error, "code", "MODEL.LOAD_FAILED"),
                "reason": "Candidate failed; one attempt to restore the previous model was made.",
            }
