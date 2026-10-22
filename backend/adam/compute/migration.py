import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, closing, contextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import portalocker

from adam import APP_VERSION
from adam.compute.catalog import Catalog, ModelProfile, config_digest, publish, read_catalog
from adam.compute.contracts import ComputeError
from adam.compute.hardware import profile as hardware_profile
from adam.compute.owned import OwnedLlamaProvider, artifact_digest, external
from adam.compute.resources import ManagedProvider
from adam.core.config import Settings
from adam.core.contracts import Contract, TraceId, new_id, utc_now
from adam.evals.security import ATTACKS, evaluate_security
from adam.evals.suite import EvalReport, evaluate, names
from adam.identity.service import IdentityService
from adam.models.base import Message, ModelProvider, closing_stream
from adam.resilience.archive import readonly, scoped
from adam.security.request import check_authority


class Benchmark(Contract):
    benchmark_id: str
    profile_id: str
    created_at: datetime
    release: str = APP_VERSION
    configuration_digest: str
    artifact_sha256: str | None
    machine_digest: str
    identity_memory_before: str
    identity_memory_after: str
    local: EvalReport
    security: EvalReport
    metrics: dict[str, float | int | None]
    healthy: bool
    note: str = "Synthetic fixtures; finite rubrics. External aliases do not attest model weights."


async def run_gate(settings: Settings) -> tuple[EvalReport, EvalReport]:
    return await evaluate(settings, real_model=True, real_rag=True), await evaluate_security(
        settings
    )


def continuity(settings: Settings) -> str:
    directory = settings.identity_dir or (
        settings.data_dir / "identity" if (settings.data_dir / "identity").exists() else None
    )
    parts: list[Any] = [IdentityService(directory).digest]
    path = scoped(settings.data_dir, "runtime.sqlite3")
    if path.exists():
        with closing(readonly(path)) as db:
            for table in ["memories", "memory_candidates"]:
                parts.extend(db.execute(f"SELECT record FROM {table} ORDER BY record").fetchall())
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def machine_digest(settings: Settings) -> str:
    hardware = hardware_profile(settings.data_dir)
    stable = [
        hardware["cpu"],
        hardware["ram_total_bytes"],
        hardware["os"],
        [(gpu["name"], gpu["vram_total_bytes"]) for gpu in hardware["gpus"]],
    ]
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


async def throughput(provider: ModelProvider, settings: Settings) -> dict[str, float | int | None]:
    started = time.perf_counter()
    first = None
    answer = ""
    async with closing_stream(
        provider.stream(
            [
                Message(
                    role="user",
                    content="Count from 1 to 24 separated by spaces. Output only the numbers.",
                )
            ],
            TraceId(new_id()),
        )
    ) as stream:
        async for chunk in stream:
            if first is None:
                first = time.perf_counter()
            answer += chunk
            if len(answer) > 4000:
                raise ComputeError("MODEL.BENCHMARK_RESPONSE_LIMIT")
    finished = time.perf_counter()
    if not answer.strip() or first is None:
        raise ComputeError("MODEL.BENCHMARK_EMPTY")
    tokens = None
    try:
        async with httpx.AsyncClient(
            base_url=settings.model.base_url, trust_env=False, timeout=5
        ) as client:
            response = await client.post(
                "/tokenize", json={"content": answer, "add_special": False}
            )
            response.raise_for_status()
            value = response.json()["tokens"]
            if isinstance(value, list) and all(type(token) is int for token in value):
                tokens = len(value)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        pass
    duration = max(finished - first, 1e-6)
    return {
        "first_token_ms": (first - started) * 1000,
        "total_ms": (finished - started) * 1000,
        "output_chars": len(answer),
        "chars_per_second_after_first": len(answer) / duration,
        "token_count": tokens,
        "tokens_per_second_after_first": tokens / duration if tokens else None,
    }


class ModelController:
    def __init__(self, manager: ManagedProvider) -> None:
        self.manager = manager
        manager.controller = self
        self.settings = manager.settings
        self.root = self.settings.data_dir
        path = scoped(self.root, "config/model-catalog.json")
        self.catalog = (
            read_catalog(path)
            if path.exists()
            else Catalog(
                profiles={"current": ModelProfile(profile_id="current", model=self.settings.model)}
            )
        )
        # Persisted selection is authoritative. An interrupted trial never becomes default.
        matching = next(
            (
                key
                for key, item in self.catalog.profiles.items()
                if config_digest(item.model) == config_digest(self.settings.model)
            ),
            None,
        )
        if matching is None:
            raise ComputeError("MODEL.CONFIGURATION_CONFLICT")
        self.active_id = matching
        self.catalog.default_id = matching
        self.pending_previous: str | None = None
        self.runner: Callable[[Settings], Awaitable[tuple[EvalReport, EvalReport]]] = run_gate
        self.measure: Callable[
            [ModelProvider, Settings], Awaitable[dict[str, float | int | None]]
        ] = throughput
        self.machine: Callable[[], str] = lambda: machine_digest(self.settings)
        self.factory: Callable[[ModelProfile], ModelProvider] = lambda item: (
            OwnedLlamaProvider(item) if item.managed else external(item.model)
        )
        self.initial_provider = manager.delegate
        self.disk_revision = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        )
        self.trial_benchmark_id: str | None = None
        if self.catalog.profiles[self.active_id].managed:
            manager.delegate = self.factory(self.catalog.profiles[self.active_id])
            manager.detached = True
        self.manager.gpu_required = self.catalog.profiles[self.active_id].device == "vulkan"

    async def startup(self) -> None:
        if self.catalog.profiles[self.active_id].managed:
            try:
                await self.manager.load()
            except ComputeError as error:
                self.manager.state, self.manager.error = "ERROR", error.code

    @contextmanager
    def disk_lock(self) -> Iterator[None]:
        path = scoped(self.root, "compute/control.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = portalocker.Lock(str(path), mode="a+b", timeout=0)
        try:
            lock.acquire()
        except portalocker.exceptions.LockException:
            raise ComputeError("MODEL.CONTROL_BUSY") from None
        accepted = False
        try:
            catalog = scoped(self.root, "config/model-catalog.json")
            revision = (
                hashlib.sha256(catalog.read_bytes()).hexdigest() if catalog.exists() else None
            )
            if revision != self.disk_revision:
                raise ComputeError("MODEL.CATALOG_STALE_RESTART_REQUIRED")
            accepted = True
            yield
        finally:
            if accepted:
                catalog = scoped(self.root, "config/model-catalog.json")
                self.disk_revision = (
                    hashlib.sha256(catalog.read_bytes()).hexdigest() if catalog.exists() else None
                )
            lock.release()

    @asynccontextmanager
    async def mutation(self) -> AsyncIterator[None]:
        with self.disk_lock():
            async with self.manager.operation():
                yield

    async def register(self, item: ModelProfile) -> dict[str, object]:
        async with self.mutation():
            if self.pending_previous:
                raise ComputeError("MODEL.LIFECYCLE_BUSY")
            if item.profile_id in self.catalog.profiles:
                raise ComputeError("MODEL.PROFILE_EXISTS")
            if len(self.catalog.profiles) >= 20:
                raise ComputeError("MODEL.CATALOG_LIMIT")
            updated = self.catalog.model_copy(deep=True)
            updated.profiles[item.profile_id] = item
            publish(self.root, "config/model-catalog.json", updated)
            self.catalog = updated
            return {"profile_id": item.profile_id, "status": "REGISTERED_NOT_APPROVED"}

    def selected(self, identifier: str) -> ModelProfile:
        try:
            return self.catalog.profiles[identifier]
        except KeyError:
            raise ComputeError("MODEL.PROFILE_NOT_FOUND") from None

    def cards(self) -> dict[str, Any]:
        return {
            "active": self.active_id,
            "default": self.catalog.default_id,
            "trial": self.pending_previous is not None,
            "previous": self.catalog.previous_id,
            "profiles": [item.model_dump(mode="json") for item in self.catalog.profiles.values()],
            "reports": self.catalog.reports,
            "note": "Declared cards; benchmark evidence is required before trial promotion.",
        }

    async def benchmark(self, identifier: str) -> dict[str, Any]:
        item = self.selected(identifier)
        async with self.mutation():
            if self.manager.observe()["mode"] == "DEGRADED":
                raise ComputeError("RESOURCE.PRESSURE")
            before = await asyncio.to_thread(continuity, self.settings)
            artifact = await asyncio.to_thread(artifact_digest, item)
            machine = await asyncio.to_thread(self.machine)
            previous = self.manager.delegate
            was_running = isinstance(previous, OwnedLlamaProvider) and previous.process is not None
            target = self.factory(item)
            # External servers are never stopped. Owned current weights can be evicted
            # during an explicit exclusive benchmark, then loaded again in finally.
            if was_running:
                await previous.unload()
            config = self.settings.model_copy(update={"model": item.model})
            try:
                started = time.perf_counter()
                health = await target.load()
                if health.status != "HEALTHY":
                    raise ComputeError("MODEL.BENCHMARK_UNAVAILABLE")
                load_ms = (time.perf_counter() - started) * 1000
                local, security = await self.runner(config)
                metrics = await self.measure(target, config)
                metrics["attach_or_load_ms"] = load_ms
                after = await asyncio.to_thread(continuity, self.settings)
                report = Benchmark(
                    benchmark_id=new_id(),
                    profile_id=identifier,
                    created_at=utc_now(),
                    configuration_digest=config_digest(item.model),
                    artifact_sha256=artifact,
                    machine_digest=machine,
                    identity_memory_before=before,
                    identity_memory_after=after,
                    local=local,
                    security=security,
                    metrics=metrics,
                    healthy=(await target.health_check()).status == "HEALTHY",
                )
                updated = self.catalog.model_copy(deep=True)
                if len(updated.reports) >= 80:
                    raise ComputeError("MODEL.REPORT_LIMIT")
                encoded = report.model_dump_json()
                updated.reports[report.benchmark_id] = {
                    "profile_id": identifier,
                    "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                }
                publish(
                    self.root,
                    f"compute/reports/{report.benchmark_id}.json",
                    {"report": json.loads(encoded)},
                )
                publish(self.root, "config/model-catalog.json", updated)
                self.catalog = updated
                return {**report.model_dump(mode="json"), "eligible": self.eligible(report, item)}
            finally:
                await target.unload()
                if was_running:
                    await self.restore_previous(previous)

    async def restore_previous(self, previous: ModelProvider) -> None:
        try:
            if (await previous.load()).status != "HEALTHY":
                raise ComputeError("MODEL.RESTORE_FAILED")
        except (MemoryError, OSError, ValueError):
            self.manager.error, self.manager.state = "MODEL.RESTORE_FAILED", "ERROR"
            raise ComputeError("MODEL.RESTORE_FAILED") from None

    def evidence(self, identifier: str) -> Benchmark:
        if identifier not in self.catalog.reports:
            raise ComputeError("MODEL.BENCHMARK_NOT_FOUND")
        path = scoped(self.root, f"compute/reports/{identifier}.json")
        try:
            if path.stat().st_size > 1024**2:
                raise ValueError
            report = Benchmark.model_validate_json(
                json.dumps(json.loads(path.read_bytes())["report"])
            )
        except (OSError, ValueError, KeyError, TypeError):
            raise ComputeError("MODEL.BENCHMARK_INVALID") from None
        if (
            hashlib.sha256(report.model_dump_json().encode()).hexdigest()
            != self.catalog.reports[identifier]["sha256"]
        ):
            raise ComputeError("MODEL.BENCHMARK_CHANGED")
        return report

    def eligible(self, report: Benchmark, item: ModelProfile) -> bool:
        return (
            report.healthy
            and report.release == APP_VERSION
            and report.configuration_digest == config_digest(item.model)
            and report.identity_memory_before == report.identity_memory_after
            and report.local.suite == "local-v1"
            and report.security.suite == "security-v1"
            and report.local.execution == "real-model;real-rag"
            and report.security.execution == "adversarial-scripted-provider"
            and report.local.model.get("model_id") == item.model.model_id
            and {case.name for case in report.local.cases} == set(names())
            and {case.name for case in report.security.cases} == set(ATTACKS)
            and report.local.passed
            and report.security.passed
            and all(case.passed for case in [*report.local.cases, *report.security.cases])
            and report.local.critical_failures == report.security.critical_failures == 0
            and max(case.duration_ms for case in report.local.cases)
            <= self.settings.compute.benchmark_max_case_ms
            and 0 <= (datetime.now(UTC) - report.created_at).total_seconds() <= 86400
        )

    async def promote(
        self, identifier: str, benchmark_id: str, acknowledge_reduced: bool
    ) -> dict[str, str]:
        if self.pending_previous or identifier == self.active_id:
            raise ComputeError("MODEL.TRIAL_CONFLICT")
        item = self.selected(identifier)
        candidate = self.evidence(benchmark_id)
        baseline_ids = [
            key
            for key, value in self.catalog.reports.items()
            if value["profile_id"] == self.active_id
        ]
        if not baseline_ids:
            raise ComputeError("MODEL.BASELINE_REQUIRED")
        baseline = self.evidence(baseline_ids[-1])
        if (
            candidate.profile_id != identifier
            or not self.eligible(candidate, item)
            or not self.eligible(baseline, self.selected(self.active_id))
        ):
            raise ComputeError("MODEL.GATES_FAILED")
        if (
            candidate.machine_digest != baseline.machine_digest
            or candidate.local.dataset_digest != baseline.local.dataset_digest
            or candidate.security.dataset_digest != baseline.security.dataset_digest
        ):
            raise ComputeError("MODEL.BENCHMARK_NOT_COMPARABLE")
        current = self.selected(self.active_id).model
        if (
            item.model.context_limit < current.context_limit
            or not set(current.languages) <= set(item.model.languages)
            or any(
                getattr(current, flag) and not getattr(item.model, flag)
                for flag in ("tools", "reasoning", "json_output")
            )
        ) and not acknowledge_reduced:
            raise ComputeError("MODEL.REDUCED_CAPABILITY_ACK_REQUIRED")
        async with self.mutation():
            if candidate.machine_digest != await asyncio.to_thread(self.machine):
                raise ComputeError("MODEL.MACHINE_CHANGED")
            if candidate.artifact_sha256 != await asyncio.to_thread(artifact_digest, item):
                raise ComputeError("MODEL.ARTIFACT_CHANGED")
            previous = self.active_id
            await self.swap(item)
            self.pending_previous = previous
            self.trial_benchmark_id = benchmark_id
            return {"status": "TRIAL", "active": self.active_id, "default": self.catalog.default_id}

    async def swap(self, item: ModelProfile, *, recovery: bool = False) -> None:
        old_error = self.manager.error
        if recovery:
            self.manager.error = None
        sample = self.manager.observe()
        self.manager.error = old_error
        if sample["mode"] == "DEGRADED":
            raise ComputeError("RESOURCE.PRESSURE")
        before = await asyncio.to_thread(continuity, self.settings)
        previous = self.manager.delegate
        old_owned = isinstance(previous, OwnedLlamaProvider) and previous.process is not None
        target = self.factory(item)
        if old_owned:
            await previous.unload()
        self.manager.state = "LOADING"
        try:
            health = await target.load()
            if health.status != "HEALTHY":
                raise ComputeError("MODEL.CANDIDATE_UNAVAILABLE")
            if await asyncio.to_thread(continuity, self.settings) != before:
                raise ComputeError("MODEL.CONTINUITY_FAILED")
            check_authority()
        except BaseException:
            await target.unload()
            if old_owned:
                await self.restore_previous(previous)
            self.manager.state = "IDLE" if not self.manager.error else "ERROR"
            raise
        self.manager.delegate = target
        self.manager.detached, self.manager.error, self.manager.failures = False, None, 0
        self.manager.gpu_required = item.device == "vulkan"
        self.manager.state = "LOADED"
        self.settings.model = item.model
        self.active_id = item.profile_id

    async def finalize(self) -> dict[str, str]:
        if self.pending_previous is None:
            raise ComputeError("MODEL.NO_TRIAL")
        async with self.mutation():
            if self.trial_benchmark_id is None:
                raise ComputeError("MODEL.GATES_FAILED")
            report = self.evidence(self.trial_benchmark_id)
            item = self.selected(self.active_id)
            if not self.eligible(report, item) or report.artifact_sha256 != await asyncio.to_thread(
                artifact_digest, item
            ):
                raise ComputeError("MODEL.GATES_FAILED")
            if (await self.manager.health_check()).status != "HEALTHY":
                raise ComputeError("MODEL.CANDIDATE_UNAVAILABLE")
            updated = self.catalog.model_copy(deep=True)
            updated.previous_id, updated.default_id = self.pending_previous, self.active_id
            publish(self.root, "config/model-catalog.json", updated)
            # Atomic selection publication is the commit point; registry metadata
            # alone cannot change the default after an interrupted finalize.
            publish(
                self.root,
                "config/model-selection.json",
                {"format": 1, "model": self.settings.model.model_dump(mode="json")},
            )
            self.catalog, self.pending_previous, self.trial_benchmark_id = updated, None, None
            return {"status": "FINALIZED", "default": self.catalog.default_id}

    async def rollback(self) -> dict[str, str]:
        previous = self.pending_previous or self.catalog.previous_id
        if previous is None:
            raise ComputeError("MODEL.NO_ROLLBACK")
        async with self.mutation():
            was_finalized = self.pending_previous is None
            await self.swap(self.selected(previous), recovery=True)
            if was_finalized:
                updated = self.catalog.model_copy(deep=True)
                updated.previous_id, updated.default_id = self.catalog.default_id, previous
                publish(self.root, "config/model-catalog.json", updated)
                publish(
                    self.root,
                    "config/model-selection.json",
                    {"format": 1, "model": self.settings.model.model_dump(mode="json")},
                )
                self.catalog = updated
            self.pending_previous, self.trial_benchmark_id = None, None
            return {"status": "ROLLED_BACK", "active": self.active_id}
