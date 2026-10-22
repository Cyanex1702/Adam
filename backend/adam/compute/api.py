import asyncio
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from adam.compute.contracts import ComputeError
from adam.compute.hardware import telemetry
from adam.compute.resources import ManagedProvider
from adam.core.contracts import Contract


class Promotion(Contract):
    benchmark_id: str
    acknowledge_reduced: bool = False


def install_compute(app: FastAPI, manager: ManagedProvider) -> Any:
    from adam.compute.catalog import ModelProfile
    from adam.compute.migration import ModelController
    from adam.compute.owned import OwnedLlamaProvider

    controller = ModelController(manager)
    app.state.models = controller

    @app.exception_handler(ComputeError)
    async def failed(request: Request, error: ComputeError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": error.code})

    @app.get("/developer/compute")
    async def status() -> dict[str, Any]:
        sample = await asyncio.to_thread(telemetry, manager.settings.data_dir)
        sample.update(
            {key: value for key, value in manager.observe().items() if key in {"mode", "reasons"}}
        )
        return {
            "lifecycle": manager.state,
            "error": manager.error,
            "ownership": "OWNED_PROCESS"
            if isinstance(manager.delegate, OwnedLlamaProvider)
            else "EXTERNAL_ADAPTER",
            "active_turns": manager.turns,
            "active_priority": manager.scheduler.active,
            "queued": len(manager.scheduler.waiters),
            "resources": sample,
            "capabilities": manager.envelope(sample),
            "model": manager.get_capabilities().model_dump(),
            "history": list(manager.samples),
        }

    @app.post("/developer/compute/load")
    async def load() -> dict[str, Any]:
        with controller.disk_lock():
            return (await manager.load()).model_dump()

    @app.post("/developer/compute/unload")
    async def unload() -> dict[str, str]:
        owned = isinstance(manager.delegate, OwnedLlamaProvider)
        with controller.disk_lock():
            await manager.unload()
        return {
            "state": manager.state,
            "effect": "OWNED_SERVER_STOPPED" if owned else "ADAPTER_DETACHED",
        }

    @app.get("/developer/models")
    async def cards() -> dict[str, Any]:
        return controller.cards()

    @app.post("/developer/models")
    async def register(body: ModelProfile) -> dict[str, object]:
        return await controller.register(body)

    @app.post("/developer/models/{identifier}/benchmark")
    async def benchmark(identifier: str) -> dict[str, Any]:
        return await controller.benchmark(identifier)

    @app.post("/developer/models/{identifier}/promote")
    async def promote(identifier: str, body: Promotion) -> dict[str, str]:
        return await controller.promote(identifier, body.benchmark_id, body.acknowledge_reduced)

    @app.post("/developer/models/finalize")
    async def finalize() -> dict[str, str]:
        return await controller.finalize()

    @app.post("/developer/models/rollback")
    async def rollback() -> dict[str, str]:
        return await controller.rollback()

    return controller
