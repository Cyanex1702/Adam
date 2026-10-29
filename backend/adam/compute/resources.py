import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal, TypeVar

from adam.compute.contracts import ComputeConfig, ComputeError
from adam.compute.hardware import gpus, telemetry
from adam.core.config import Settings
from adam.core.contracts import AdamError, ErrorEnvelope, TraceId
from adam.models.base import Message, ModelCard, ModelHealth, ModelProvider, closing_stream

Priority = Literal["CRITICAL", "INTERACTIVE", "HIGH", "NORMAL", "LOW", "IDLE"]
PRIORITIES = ["CRITICAL", "INTERACTIVE", "HIGH", "NORMAL", "LOW", "IDLE"]
T = TypeVar("T")


class PriorityScheduler:
    """Non-preemptive operations; queued work yields at safe operation boundaries."""

    def __init__(self, config: ComputeConfig) -> None:
        self.config = config
        self.condition = asyncio.Condition()
        self.waiters: list[tuple[int, int]] = []
        self.sequence = 0
        self.active: str | None = None

    @asynccontextmanager
    async def slot(self, priority: Priority) -> AsyncIterator[None]:
        ticket = (PRIORITIES.index(priority), self.sequence)
        self.sequence += 1
        acquired = False
        async with self.condition:
            if len(self.waiters) >= self.config.queue_limit:
                raise ComputeError("RESOURCE.QUEUE_FULL")
            self.waiters.append(ticket)
            try:
                async with asyncio.timeout(self.config.queue_timeout_seconds):
                    await self.condition.wait_for(
                        lambda: self.active is None and ticket == min(self.waiters)
                    )
                self.active = priority
                acquired = True
            except TimeoutError:
                raise ComputeError("RESOURCE.QUEUE_TIMEOUT") from None
            finally:
                self.waiters.remove(ticket)
                self.condition.notify_all()
        try:
            yield
        finally:
            if acquired:
                async with self.condition:
                    self.active = None
                    self.condition.notify_all()

    async def run(self, priority: Priority, function: Callable[[], T]) -> T:
        async with self.slot(priority):
            # Cancellation cannot release the slot while its worker still mutates data.
            worker = asyncio.create_task(asyncio.to_thread(function))
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                try:
                    while not worker.done():
                        try:
                            await asyncio.shield(worker)
                        except asyncio.CancelledError:
                            continue
                finally:
                    raise


class ManagedProvider(ModelProvider):
    def __init__(self, provider: ModelProvider, settings: Settings) -> None:
        self.delegate = provider
        self.settings = settings
        self.config = settings.compute
        from adam.resilience.archive import scoped

        preference = scoped(settings.data_dir, "config/performance.json")
        if preference.is_file():
            import json

            if preference.stat().st_size > 1024:
                raise ComputeError("CONFIG.PERFORMANCE_INVALID")
            saved = json.loads(preference.read_bytes())
            if set(saved) != {"mode"} or saved["mode"] not in {"eco", "priority"}:
                raise ComputeError("CONFIG.PERFORMANCE_INVALID")
            self.config.mode = saved["mode"]
        self.scheduler = PriorityScheduler(self.config)
        self.state = "AVAILABLE"
        self.detached = False
        self.operation_active = False
        self.operation_idle = asyncio.Event()
        self.operation_idle.set()
        self.admission_lock = asyncio.Lock()
        self.admission_waiters = 0
        self.operation_started: float | None = None
        self.turns = 0
        self.failures = 0
        self.error: str | None = None
        self.retry_at = 0.0
        self.sampler: Callable[[], dict[str, Any]] = lambda: telemetry(settings.data_dir, gpu=False)
        self.samples: deque[dict[str, Any]] = deque(maxlen=60)
        self.gpu_probe: Callable[[], list[dict[str, Any]]] = gpus
        self.gpu_required = self.config.gpu_admission
        self.controller: Any = None
        self.last_health: ModelHealth | None = None
        self.routing_lock = asyncio.Lock()
        self.routing_waiters = 0

    def get_capabilities(self) -> ModelCard:
        return self.delegate.get_capabilities()

    def observe(self) -> dict[str, Any]:
        sample = self.sampler()
        reasons = []
        available, percent, disk = (
            sample.get("ram_available_bytes"),
            sample.get("ram_used_percent"),
            sample.get("disk_free_bytes"),
        )
        if available is not None and available < self.config.min_free_ram_mib * 1024**2:
            reasons.append("RESOURCE.RAM_PRESSURE")
        pressure_limit = (
            min(97.0, self.config.ram_pressure_percent + 3)
            if self.config.mode == "priority"
            else self.config.ram_pressure_percent
        )
        if percent is not None and percent >= pressure_limit:
            reasons.append("RESOURCE.RAM_PRESSURE")
        if disk is not None and disk < self.config.min_free_disk_mib * 1024**2:
            reasons.append("RESOURCE.STORAGE_PRESSURE")
        if available is None or percent is None or disk is None:
            reasons.append("RESOURCE.TELEMETRY_UNAVAILABLE")
        if self.gpu_required:
            devices = self.gpu_probe()
            sample["gpus"] = devices
            margins = [
                device["vram_total_bytes"] - device["vram_used_bytes"]
                for device in devices
                if device.get("vram_total_bytes") is not None
                and device.get("vram_used_bytes") is not None
            ]
            if not margins:
                reasons.append("RESOURCE.GPU_TELEMETRY_UNAVAILABLE")
            elif max(margins) < self.config.min_free_vram_mib * 1024**2:
                reasons.append("RESOURCE.VRAM_PRESSURE")
        if self.error and self.error.startswith("RESOURCE."):
            reasons.append(self.error)
        mode = "DEGRADED" if reasons else "NORMAL" if available is not None else "UNKNOWN"
        result = {
            **sample,
            "mode": mode,
            "reasons": sorted(set(reasons)),
            "performance_mode": self.config.mode,
            "limits": {
                "min_free_ram_mib": self.config.min_free_ram_mib,
                "ram_pressure_percent": pressure_limit,
                "min_free_disk_mib": self.config.min_free_disk_mib,
            },
        }
        self.samples.append(result)
        return result

    def admit(self) -> None:
        if self.operation_active:
            raise ComputeError("MODEL.LIFECYCLE_BUSY")
        if self.detached:
            raise ComputeError("MODEL.NOT_LOADED")
        if self.error:
            raise ComputeError("RESOURCE.RECOVERY_REQUIRED")
        if self.observe()["mode"] == "DEGRADED":
            raise ComputeError("RESOURCE.PRESSURE")

    def fail(self, code: str) -> None:
        self.failures += 1
        if code == "RESOURCE.OOM" or self.failures >= self.config.failure_limit:
            self.error = code
            self.state = "ERROR"
            self.retry_at = time.monotonic() + self.config.cooldown_seconds

    @asynccontextmanager
    async def turn(self, text: str = "") -> AsyncIterator[None]:
        if not self.controller or not self.controller.library.state.automatic:
            async with self._active_turn():
                yield
            return
        if self.routing_waiters >= self.config.queue_limit:
            raise ComputeError("RESOURCE.QUEUE_FULL")
        self.routing_waiters += 1
        try:
            async with self.routing_lock:
                if text:
                    await self.controller.library.route(text)
                async with self._active_turn():
                    yield
        finally:
            self.routing_waiters -= 1

    @asynccontextmanager
    async def _active_turn(self) -> AsyncIterator[None]:
        if self.admission_waiters >= self.config.queue_limit:
            raise ComputeError("RESOURCE.QUEUE_FULL")
        self.admission_waiters += 1
        try:
            async with asyncio.timeout(self.config.queue_timeout_seconds):
                # Serialize recovery before reserving a turn. Waiting requests do
                # not count as active inference and cannot block the load they need.
                async with self.admission_lock:
                    await self.operation_idle.wait()
                    if self.error == "RESOURCE.PRESSURE" and time.monotonic() >= self.retry_at:
                        from adam.compute.owned import OwnedLlamaProvider

                        if isinstance(self.delegate, OwnedLlamaProvider) and not self.turns:
                            self.error = None
                            try:
                                recovered = self.observe()["mode"] != "DEGRADED"
                            finally:
                                self.error = "RESOURCE.PRESSURE"
                            if recovered:
                                # A manual reload can begin while recovery waits
                                # for background work. Recheck both reservations
                                # after every await, and share a completed reload.
                                while (
                                    self.operation_active
                                    or self.scheduler.active
                                    or self.scheduler.waiters
                                ):
                                    await self.operation_idle.wait()
                                    async with self.scheduler.condition:
                                        await self.scheduler.condition.wait_for(
                                            lambda: self.scheduler.active is None
                                            and not self.scheduler.waiters
                                        )
                                if self.error == "RESOURCE.PRESSURE":
                                    try:
                                        await self.load()
                                    except ComputeError as error:
                                        self.error, self.state = error.code, "ERROR"
                                        self.retry_at = (
                                            time.monotonic() + self.config.cooldown_seconds
                                        )
                    self.turns += 1
        except TimeoutError:
            raise ComputeError("RESOURCE.QUEUE_TIMEOUT") from None
        finally:
            self.admission_waiters -= 1
        try:
            yield
        finally:
            self.turns -= 1

    @asynccontextmanager
    async def operation(self) -> AsyncIterator[None]:
        if self.operation_active or self.turns or self.scheduler.active or self.scheduler.waiters:
            raise ComputeError("MODEL.LIFECYCLE_BUSY")
        self.operation_active = True
        self.operation_started = time.monotonic()
        self.operation_idle.clear()
        try:
            yield
        finally:
            self.operation_active = False
            self.operation_started = None
            self.operation_idle.set()

    def activity(self) -> dict[str, Any]:
        return {
            "operation_active": self.operation_active,
            "operation_seconds": round(time.monotonic() - self.operation_started, 1)
            if self.operation_started is not None
            else None,
            "active_turns": self.turns,
            "waiting_for_model": self.admission_waiters,
            "active_priority": self.scheduler.active,
            "queued_inference": len(self.scheduler.waiters),
        }

    async def health_check(self) -> ModelHealth:
        # Admission failures are transient, not a permanent provider-error latch.
        if self.error == "RESOURCE.PRESSURE":
            from adam.compute.owned import OwnedLlamaProvider

            self.error = None
            if self.observe()["mode"] == "DEGRADED" or isinstance(
                self.delegate, OwnedLlamaProvider
            ):
                self.error = "RESOURCE.PRESSURE"
        if self.error or self.detached:
            return ModelHealth(
                status="DEGRADED",
                model_id=self.get_capabilities().model_id,
                reason=self.error or "MODEL.NOT_LOADED",
            )
        delegate = self.delegate
        health = await delegate.health_check()
        if delegate is self.delegate and not self.operation_active:
            self.last_health = health
        return health

    async def count_tokens(self, messages: list[Message]) -> int:
        return await self.delegate.count_tokens(messages)

    async def load(self) -> ModelHealth:
        async with self.operation():
            return await self._load()

    async def _load(self) -> ModelHealth:
        """Load within an already reserved lifecycle operation."""
        if time.monotonic() < self.retry_at:
            raise ComputeError("RESOURCE.COOLDOWN")
        old_error = self.error
        self.error = None
        if self.observe()["mode"] == "DEGRADED":
            self.error = old_error
            raise ComputeError("RESOURCE.PRESSURE")
        self.state = "LOADING"
        try:
            health = await self.delegate.load()
        except asyncio.CancelledError:
            self.detached, self.error, self.state = True, "MODEL.LOAD_CANCELLED", "ERROR"
            self.retry_at = 0.0
            raise
        except (MemoryError, OSError, ValueError) as error:
            self.error = (
                error.code
                if isinstance(error, ComputeError)
                else ("RESOURCE.OOM" if isinstance(error, MemoryError) else "RESOURCE.LOAD_FAILED")
            )
            self.state = "ERROR"
            self.retry_at = time.monotonic() + self.config.cooldown_seconds
            raise ComputeError(self.error) from None
        self.last_health = health
        if health.status != "HEALTHY":
            self.error, self.state = health.reason or "MODEL.UNAVAILABLE", "ERROR"
            self.retry_at = time.monotonic() + self.config.cooldown_seconds
        else:
            self.detached, self.error, self.failures = False, None, 0
            self.state = "LOADED"
        return health

    async def set_mode(self, mode: Literal["eco", "priority"]) -> dict[str, object]:
        from adam.compute.catalog import publish
        from adam.compute.owned import OwnedLlamaProvider

        if self.controller is None:
            raise ComputeError("MODEL.CONTROLLER_UNAVAILABLE")
        with self.controller.disk_lock():
            async with self.operation():
                reload = (
                    isinstance(self.delegate, OwnedLlamaProvider)
                    and self.delegate.process is not None
                )
                if isinstance(self.delegate, OwnedLlamaProvider):
                    await self.delegate.unload()
                    self.detached = True
                publish(self.settings.data_dir, "config/performance.json", {"mode": mode})
                self.config.mode = mode
                if isinstance(self.delegate, OwnedLlamaProvider):
                    self.delegate.mode = mode
                if reload:
                    await self._load()
        return {
            "mode": mode,
            "model_reloaded": reload,
            "scope": (
                "ADAM-owned inference process only; other apps are never closed or reprioritized."
            ),
        }

    async def unload(self) -> None:
        async with self.operation():
            self.state = "UNLOADING"
            try:
                await self.delegate.unload()
            finally:
                self.detached = True
                self.state = "AVAILABLE" if not self.error else "ERROR"

    async def background(self, function: Callable[[], T]) -> T:
        if self.operation_active:
            raise ComputeError("MODEL.LIFECYCLE_BUSY")
        if self.observe()["mode"] == "DEGRADED":
            raise ComputeError("RESOURCE.BACKGROUND_PAUSED")
        try:

            def admitted() -> T:
                if self.observe()["mode"] == "DEGRADED":
                    raise ComputeError("RESOURCE.BACKGROUND_PAUSED")
                return function()

            return await self.scheduler.run("LOW", admitted)
        except MemoryError:
            self.fail("RESOURCE.OOM")
            raise ComputeError("RESOURCE.OOM") from None

    def envelope(self, sample: dict[str, Any] | None = None) -> dict[str, str]:
        resource = sample or self.observe()
        card = self.get_capabilities()
        return {
            "text": "AVAILABLE"
            if not self.detached and not self.error and resource["mode"] != "DEGRADED"
            else "DEGRADED",
            "memory": "AVAILABLE",
            "tools": "AVAILABLE_WITH_APPROVAL",
            "voice": "CONFIGURED" if self.settings.features.voice else "UNAVAILABLE",
            "vision": "UNAVAILABLE",
            "deep_reasoning": "CONFIGURED_UNTESTED" if card.reasoning else "REDUCED",
            "model_tools": "CONFIGURED_UNTESTED" if card.tools else "UNAVAILABLE",
        }

    async def stream(self, messages: list[Message], trace_id: TraceId) -> AsyncIterator[str]:
        try:
            async with self.scheduler.slot("INTERACTIVE"):
                self.admit()
                self.state = "ACTIVE"
                try:
                    async with closing_stream(self.delegate.stream(messages, trace_id)) as stream:
                        async for token in stream:
                            yield token
                    self.failures = 0
                except MemoryError:
                    self.fail("RESOURCE.OOM")
                    raise ComputeError("RESOURCE.OOM") from None
                except AdamError as error:
                    if error.error.code in {"MODEL.OOM", "MODEL.UNAVAILABLE", "MODEL.TIMEOUT"}:
                        self.fail(
                            "RESOURCE.OOM" if error.error.code == "MODEL.OOM" else error.error.code
                        )
                    raise
                finally:
                    if self.state != "ERROR":
                        self.state = "IDLE"
        except ComputeError as error:
            raise AdamError(
                ErrorEnvelope(
                    code=error.code,
                    trace_id=trace_id,
                    message="The resource or model check failed: "
                    + error.code
                    + (
                        ". Open Diagnostics or use /diagnostics for measured readings and "
                        "recovery steps."
                    ),
                    retryable=error.code in {"RESOURCE.PRESSURE", "RESOURCE.BACKGROUND_PAUSED"},
                )
            ) from None
