import asyncio
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from adam.compute.contracts import ComputeError
from adam.compute.hardware import telemetry
from adam.compute.resources import ManagedProvider
from adam.core.contracts import Contract


class Promotion(Contract):
    benchmark_id: str
    acknowledge_reduced: bool = False


class Performance(Contract):
    mode: Literal["eco", "priority"]


class Device(Contract):
    device: Literal["cpu", "vulkan"]


class Scan(Contract):
    folder: str | None = Field(default=None, max_length=1024)


class LocalApproval(Contract):
    id: str = Field(pattern=r"^[a-f0-9]{20}$")
    role: Literal["quick", "balanced", "reasoning"]


class Automatic(Contract):
    enabled: bool


class Selection(Contract):
    id: str = Field(pattern=r"^[a-f0-9]{20}$")


def install_compute(app: FastAPI, manager: ManagedProvider) -> Any:
    from adam.compute.catalog import ModelProfile
    from adam.compute.migration import ModelController
    from adam.compute.owned import OwnedLlamaProvider

    controller = ModelController(manager)
    app.state.models = controller

    def owner(request: Request) -> None:
        from adam.security.auth import AuthError
        from adam.security.gateway import request_token
        from adam.security.request import REMOTE_DEVICE, check_authority

        if app.state.auth.resolve(request_token(request)).mode != "owner" or REMOTE_DEVICE.get():
            raise AuthError("POLICY.OWNER_REQUIRED")
        check_authority()

    @app.get("/diagnostics")
    async def diagnostics(request: Request) -> dict[str, Any]:
        from adam.compute.diagnostics import report

        owner(request)
        return await asyncio.to_thread(report, manager.settings, manager)

    @app.get("/performance")
    async def performance(request: Request) -> dict[str, Any]:
        owner(request)
        return {"mode": manager.config.mode, "resources": await asyncio.to_thread(manager.observe)}

    @app.post("/performance")
    async def configure_performance(request: Request, value: Performance) -> dict[str, object]:
        owner(request)
        return await manager.set_mode(value.mode)

    @app.post("/model/reload")
    async def reload_model(request: Request) -> dict[str, Any]:
        owner(request)
        with controller.disk_lock():
            return (await manager.load()).model_dump()

    @app.post("/model/device")
    async def configure_device(request: Request, value: Device) -> dict[str, Any]:
        owner(request)
        return await controller.set_device(value.device)

    @app.get("/models/library")
    async def library(request: Request) -> dict[str, Any]:
        owner(request)
        return controller.library.status()

    @app.post("/models/scan")
    async def scan(request: Request, value: Scan) -> dict[str, Any]:
        owner(request)
        async with controller.library.lock:
            return await asyncio.to_thread(controller.library.scan, value.folder)

    @app.post("/models/approve")
    async def approve_local(request: Request, value: LocalApproval) -> dict[str, Any]:
        owner(request)
        async with controller.library.lock:
            return await controller.library.approve(value.id, value.role)

    @app.post("/models/automatic")
    async def automatic(request: Request, value: Automatic) -> dict[str, Any]:
        owner(request)
        async with controller.library.lock:
            if controller.library.error:
                raise ComputeError(controller.library.error)
            controller.library.state.automatic = value.enabled
            controller.library.save()
            return controller.library.status()

    @app.post("/models/select")
    async def select_local(request: Request, value: Selection) -> dict[str, Any]:
        owner(request)
        async with controller.library.lock:
            return await controller.library.activate(value.id)

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
