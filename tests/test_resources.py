import asyncio

import httpx
import pytest
from adam.api.app import create_app
from adam.compute.contracts import ComputeConfig, ComputeError
from adam.compute.resources import ManagedProvider, PriorityScheduler
from adam.core.config import Settings
from adam.core.contracts import AdamError, TraceId, new_id
from adam.core.runtime import ChatRequest, Runtime
from adam.evals.suite import ProbeProvider
from adam.models.base import Message
from adam.models.llama_cpp import LlamaCppProvider
from fastapi.testclient import TestClient


def healthy():
    return {
        "ram_available_bytes": 4 * 1024**3,
        "ram_used_percent": 50,
        "disk_free_bytes": 4 * 1024**3,
    }


def manager(root, provider=None):
    selected = ManagedProvider(provider or ProbeProvider(), Settings(data_dir=root))
    selected.sampler = healthy
    return selected


def test_scheduler_prefers_interactive_and_cleans_cancelled_waiters():
    async def scenario():
        scheduler = PriorityScheduler(ComputeConfig())
        results = []

        async def work(priority):
            async with scheduler.slot(priority):
                results.append(priority)

        async with scheduler.slot("NORMAL"):
            background = asyncio.create_task(work("LOW"))
            interactive = asyncio.create_task(work("INTERACTIVE"))
            cancelled = asyncio.create_task(work("IDLE"))
            await asyncio.sleep(0)
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
        await asyncio.gather(background, interactive)
        assert results == ["INTERACTIVE", "LOW"]
        assert scheduler.active is None and scheduler.waiters == []

    asyncio.run(scenario())


def test_scheduler_queue_limit_and_cancellation_wait_for_worker():
    async def scenario():
        import threading

        scheduler = PriorityScheduler(ComputeConfig(queue_limit=1))
        async with scheduler.slot("NORMAL"):
            queued = asyncio.create_task(scheduler.run("LOW", lambda: None))
            await asyncio.sleep(0)
            with pytest.raises(ComputeError, match="QUEUE_FULL"):
                async with scheduler.slot("INTERACTIVE"):
                    pass
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
        started, release = threading.Event(), threading.Event()

        def slow_write():
            started.set()
            assert release.wait(5)

        running = asyncio.create_task(scheduler.run("LOW", slow_write))
        await asyncio.to_thread(started.wait, 5)
        running.cancel()
        await asyncio.sleep(0)
        assert scheduler.active == "LOW"
        running.cancel()
        await asyncio.sleep(0)
        assert scheduler.active == "LOW" and not running.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert scheduler.active is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "sample",
    [
        {"ram_available_bytes": 1, "ram_used_percent": 20, "disk_free_bytes": 10**10},
        {"ram_available_bytes": 10**10, "ram_used_percent": 99, "disk_free_bytes": 10**10},
        {"ram_available_bytes": 10**10, "ram_used_percent": 20, "disk_free_bytes": 1},
    ],
)
def test_pressure_blocks_model_and_background_but_preserves_explicit_memory(tmp_path, sample):
    selected = manager(tmp_path)
    selected.sampler = lambda: sample
    runtime = Runtime(selected.settings, selected)
    try:
        result = asyncio.run(runtime.chat(ChatRequest(text="ordinary generation")))
        assert result.payload["error"]["code"] == "RESOURCE.PRESSURE"
        saved = asyncio.run(
            runtime.chat(ChatRequest(text="/remember preference editor = safe state"))
        )
        assert saved.event_type == "agent.completed"
        assert selected.envelope()["text"] == "DEGRADED"
        with pytest.raises(ComputeError, match="BACKGROUND_PAUSED"):
            asyncio.run(selected.background(lambda: None))
    finally:
        runtime.retrieval.close()


def test_oom_latches_without_retry_and_requires_explicit_reload(tmp_path):
    class OutOfMemory(ProbeProvider):
        calls = 0

        async def stream(self, messages, trace_id):
            self.calls += 1
            raise MemoryError("private allocation detail")
            yield "unreachable"

    provider = OutOfMemory()
    selected = manager(tmp_path, provider)
    selected.config.cooldown_seconds = 0

    async def scenario():
        for expected in ["RESOURCE.OOM", "RESOURCE.RECOVERY_REQUIRED"]:
            with pytest.raises(AdamError) as caught:
                await selected.generate(
                    [Message(role="user", content="fixture")], TraceId(new_id())
                )
            assert caught.value.error.code == expected
            assert "private" not in caught.value.error.model_dump_json()
        assert provider.calls == 1 and selected.state == "ERROR"
        selected.delegate = ProbeProvider()
        assert (await selected.load()).status == "HEALTHY"
        assert selected.state == "LOADED" and selected.error is None

    asyncio.run(scenario())


def test_external_oom_is_classified_and_cooldown_prevents_loop(tmp_path):
    async def response(request):
        return httpx.Response(500, json={"error": "CUDA out of memory synthetic"})

    provider = LlamaCppProvider(Settings().model, httpx.MockTransport(response))
    selected = manager(tmp_path, provider)
    with pytest.raises(AdamError) as caught:
        asyncio.run(selected.generate([Message(role="user", content="fixture")], TraceId(new_id())))
    assert caught.value.error.code == "MODEL.OOM" and selected.error == "RESOURCE.OOM"
    with pytest.raises(ComputeError, match="COOLDOWN"):
        asyncio.run(selected.load())


@pytest.mark.parametrize(
    "devices,expected",
    [
        ([], "RESOURCE.GPU_TELEMETRY_UNAVAILABLE"),
        (
            [{"vram_total_bytes": 8 * 1024**3, "vram_used_bytes": 8 * 1024**3}],
            "RESOURCE.VRAM_PRESSURE",
        ),
    ],
)
def test_gpu_admission_requires_measured_headroom(tmp_path, devices, expected):
    selected = manager(tmp_path)
    selected.gpu_required = True
    selected.gpu_probe = lambda: devices
    assert expected in selected.observe()["reasons"]
    with pytest.raises(ComputeError, match="PRESSURE"):
        selected.admit()


def test_lifecycle_refuses_busy_turn_and_detach_does_not_erase_state(tmp_path):
    selected = manager(tmp_path)
    runtime = Runtime(selected.settings, selected)

    async def scenario():
        await runtime.chat(ChatRequest(text="/remember preference editor = SyntheticStudio"))
        async with selected.turn():
            with pytest.raises(ComputeError, match="LIFECYCLE_BUSY"):
                await selected.unload()
        identity = runtime.identity.digest
        await selected.unload()
        assert selected.detached and (await selected.health_check()).reason == "MODEL.NOT_LOADED"
        assert runtime.memories.search("editor")[0].content == "SyntheticStudio"
        assert runtime.identity.digest == identity
        await selected.load()
        assert selected.state == "LOADED"

    try:
        asyncio.run(scenario())
    finally:
        runtime.retrieval.close()


def test_compute_routes_are_owner_elevated_and_fixed_errors(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), ProbeProvider())
    password = "synthetic-compute-owner-password"
    app.state.auth.initialize(password)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/developer/compute").status_code == 401
        client.post("/auth/login", json={"password": password})
        assert client.post("/developer/compute/unload").status_code == 403
        client.post("/auth/elevate", json={"password": password})
        assert client.post("/developer/compute/unload").json()["effect"] == "ADAPTER_DETACHED"
        assert client.get("/developer/compute").json()["capabilities"]["text"] == "DEGRADED"
        assert client.post("/developer/compute/load").json()["status"] == "HEALTHY"
        client.post("/auth/switch", json={"mode": "guest"})
        assert client.get("/developer/hardware").status_code == 403


def test_background_rechecks_pressure_after_waiting(tmp_path):
    selected = manager(tmp_path)
    calls = []

    async def scenario():
        async with selected.scheduler.slot("INTERACTIVE"):
            queued = asyncio.create_task(selected.background(lambda: calls.append("write")))
            await asyncio.sleep(0)
            selected.sampler = lambda: {"ram_available_bytes": 1}
        with pytest.raises(ComputeError, match="BACKGROUND_PAUSED"):
            await queued
        assert calls == [] and selected.scheduler.active is None

    asyncio.run(scenario())
