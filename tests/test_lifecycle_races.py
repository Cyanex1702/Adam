"""User-visible lifecycle regressions, with deterministic operation barriers."""

import asyncio

import pytest
from adam.compute.contracts import ComputeError
from adam.compute.resources import ManagedProvider
from adam.core.config import Settings
from adam.core.runtime import ChatRequest, Runtime
from adam.evals.suite import ProbeProvider
from adam.models.base import ModelHealth


def managed(tmp_path, provider):
    manager = ManagedProvider(provider, Settings(data_dir=tmp_path))
    manager.sampler = lambda: {
        "ram_available_bytes": 8 * 1024**3,
        "ram_used_percent": 40,
        "disk_free_bytes": 8 * 1024**3,
    }
    return manager


def test_chat_waits_for_startup_load_instead_of_lifecycle_busy(tmp_path):
    async def scenario():
        entered, finish = asyncio.Event(), asyncio.Event()

        class Loading(ProbeProvider):
            async def load(self):
                entered.set()
                await finish.wait()
                return ModelHealth(status="HEALTHY", model_id="probe")

        manager = managed(tmp_path, Loading())
        runtime = Runtime(manager.settings, manager)
        try:
            load = asyncio.create_task(manager.load())
            await entered.wait()
            chat = asyncio.create_task(runtime.chat(ChatRequest(text="hi")))
            await asyncio.sleep(0)
            assert not chat.done(), "Startup loading must queue chat, not fail it"
            finish.set()
            await load
            event = await chat
            assert event.event_type == "agent.completed"
            assert manager.turns == 0 and not manager.operation_active
        finally:
            finish.set()
            runtime.retrieval.close()

    asyncio.run(scenario())


def test_cancelled_load_does_not_leave_false_loading_state(tmp_path):
    async def scenario():
        entered = asyncio.Event()

        class Loading(ProbeProvider):
            async def load(self):
                entered.set()
                await asyncio.Event().wait()

        manager = managed(tmp_path, Loading())
        task = asyncio.create_task(manager.load())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not manager.operation_active
        assert manager.state != "LOADING"
        manager.delegate = ProbeProvider()
        assert (await manager.load()).status == "HEALTHY"

    asyncio.run(scenario())


def test_pressure_recovery_is_shared_by_concurrent_chat_requests(tmp_path, monkeypatch):
    async def scenario():
        entered, finish = asyncio.Event(), asyncio.Event()

        class Recovering(ProbeProvider):
            calls = 0

            async def load(self):
                self.calls += 1
                entered.set()
                await finish.wait()
                return ModelHealth(status="HEALTHY", model_id="probe")

        # Exercise the exact owned-only recovery branch without starting a process.
        monkeypatch.setattr("adam.compute.owned.OwnedLlamaProvider", Recovering)
        provider = Recovering()
        manager = managed(tmp_path, provider)
        manager.error, manager.state, manager.detached = "RESOURCE.PRESSURE", "ERROR", True

        async def turn():
            async with manager.turn():
                await asyncio.sleep(0)

        first = asyncio.create_task(turn())
        await entered.wait()
        second = asyncio.create_task(turn())
        await asyncio.sleep(0)
        finish.set()
        await asyncio.gather(first, second)
        assert provider.calls == 1
        assert manager.error is None and manager.turns == 0

    asyncio.run(scenario())


def test_reload_during_active_turn_remains_blocked(tmp_path):
    async def scenario():
        manager = managed(tmp_path, ProbeProvider())
        async with manager.turn():
            with pytest.raises(ComputeError, match="MODEL.LIFECYCLE_BUSY"):
                await manager.load()
        assert not manager.operation_active and manager.turns == 0
        assert (await manager.load()).status == "HEALTHY"

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_waiting_chat_timeout_or_stop_does_not_cancel_shared_model_load(tmp_path, cancel):
    async def scenario():
        entered, finish = asyncio.Event(), asyncio.Event()

        class Loading(ProbeProvider):
            async def load(self):
                entered.set()
                await finish.wait()
                return ModelHealth(status="HEALTHY", model_id="probe")

        manager = managed(tmp_path, Loading())
        manager.config.queue_timeout_seconds = 0.03
        runtime = Runtime(manager.settings, manager)
        try:
            load = asyncio.create_task(manager.load())
            await entered.wait()
            chat = asyncio.create_task(runtime.chat(ChatRequest(text="hi")))
            await asyncio.sleep(0)
            if cancel:
                chat.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await chat
            else:
                event = await chat
                assert event.payload["error"]["code"] == "RESOURCE.QUEUE_TIMEOUT"
            assert manager.operation_active and not load.done()
            assert manager.admission_waiters == 0 and manager.turns == 0
            finish.set()
            await load
            assert (await runtime.chat(ChatRequest(text="hi"))).event_type == "agent.completed"
        finally:
            finish.set()
            runtime.retrieval.close()

    asyncio.run(scenario())


def test_startup_reserves_loading_before_app_accepts_requests(tmp_path):
    from adam.api.app import create_app

    async def scenario():
        finish = asyncio.Event()

        class Loading(ProbeProvider):
            async def load(self):
                await finish.wait()
                return ModelHealth(status="HEALTHY", model_id="probe")

        app = create_app(Settings(data_dir=tmp_path), Loading())
        manager = app.state.models.manager
        manager.sampler = lambda: {
            "ram_available_bytes": 8 * 1024**3,
            "ram_used_percent": 40,
            "disk_free_bytes": 8 * 1024**3,
        }
        async with app.router.lifespan_context(app):
            assert manager.operation_active
            chat = asyncio.create_task(app.state.runtime.chat(ChatRequest(text="hi")))
            await asyncio.sleep(0)
            assert not chat.done()
            finish.set()
            assert (await chat).event_type == "agent.completed"
            assert manager.error is None

    asyncio.run(scenario())


def test_wait_queue_capacity_and_cancelled_waiter_cleanup(tmp_path):
    async def scenario():
        manager = managed(tmp_path, ProbeProvider())
        manager.config.queue_limit = 1

        async def turn():
            async with manager.turn():
                pass

        async with manager.operation():
            waiting = asyncio.create_task(turn())
            await asyncio.sleep(0)
            with pytest.raises(ComputeError, match="RESOURCE.QUEUE_FULL"):
                await turn()
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert manager.admission_waiters == 0
        await turn()
        assert manager.turns == 0 and manager.operation_idle.is_set()

    asyncio.run(scenario())


def test_health_poll_does_not_lose_owned_pressure_recovery(tmp_path, monkeypatch):
    class Recovering(ProbeProvider):
        calls = 0

        async def load(self):
            self.calls += 1
            return ModelHealth(status="HEALTHY", model_id="probe")

    monkeypatch.setattr("adam.compute.owned.OwnedLlamaProvider", Recovering)
    provider = Recovering()
    manager = managed(tmp_path, provider)
    manager.error, manager.detached, manager.state = "RESOURCE.PRESSURE", True, "ERROR"

    async def scenario():
        await manager.health_check()
        assert manager.error == "RESOURCE.PRESSURE"
        async with manager.turn():
            assert manager.error is None and not manager.detached
        assert provider.calls == 1

    asyncio.run(scenario())


def test_recovery_waits_for_background_and_survives_cancelled_waiter(tmp_path, monkeypatch):
    class Recovering(ProbeProvider):
        calls = 0

        async def load(self):
            self.calls += 1
            return ModelHealth(status="HEALTHY", model_id="probe")

    monkeypatch.setattr("adam.compute.owned.OwnedLlamaProvider", Recovering)
    provider = Recovering()
    manager = managed(tmp_path, provider)
    manager.error, manager.detached = "RESOURCE.PRESSURE", True

    async def turn():
        async with manager.turn():
            pass

    async def scenario():
        async with manager.scheduler.slot("LOW"):
            cancelled = asyncio.create_task(turn())
            await asyncio.sleep(0)
            assert not cancelled.done() and provider.calls == 0
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            assert manager.error == "RESOURCE.PRESSURE"
            resumed = asyncio.create_task(turn())
            await asyncio.sleep(0)
            assert not resumed.done()
        await resumed
        assert provider.calls == 1 and manager.error is None
        assert manager.turns == 0 and manager.admission_waiters == 0

    asyncio.run(scenario())


def test_manual_reload_wins_while_recovery_waits_for_background(tmp_path, monkeypatch):
    class Recovering(ProbeProvider):
        calls = 0

        async def load(self):
            self.calls += 1
            return ModelHealth(status="HEALTHY", model_id="probe")

    monkeypatch.setattr("adam.compute.owned.OwnedLlamaProvider", Recovering)
    provider = Recovering()
    manager = managed(tmp_path, provider)
    manager.error, manager.detached = "RESOURCE.PRESSURE", True

    async def turn():
        async with manager.turn():
            assert not manager.operation_active
            assert manager.error is None

    async def scenario():
        async with manager.scheduler.slot("LOW"):
            waiting = asyncio.create_task(turn())
            await asyncio.sleep(0)
        # Reserve a manual reload before the waiting recovery resumes.
        async with manager.operation():
            await asyncio.sleep(0)
            assert not waiting.done()
            manager.error, manager.detached = None, False
        await waiting
        assert provider.calls == 0  # Reuse the manual reload; do not load twice.
        assert manager.turns == 0 and manager.admission_waiters == 0

    asyncio.run(scenario())
