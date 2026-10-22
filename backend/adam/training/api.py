import asyncio
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from adam.core.contracts import Contract, new_id
from adam.core.storage import ConversationStore
from adam.evals.suite import EvalReport
from adam.observability.service import TraceService
from adam.security.auth import AuthError
from adam.security.gateway import RuntimeProxy, request_token
from adam.security.request import REMOTE_DEVICE, check_authority
from adam.training.service import Example, Training, TrainingError, assess


class Enabled(Contract):
    enabled: bool


class Identifier(Contract):
    id: str = Field(pattern=r"^[a-f0-9-]{36}$")


class Comparison(Contract):
    base: EvalReport
    candidate: EvalReport
    target: str = Field(min_length=1, max_length=80)


def install_training(app: FastAPI) -> None:
    runtime = RuntimeProxy()

    def service(request: Request) -> Training:
        principal = app.state.auth.resolve(request_token(request))
        if REMOTE_DEVICE.get() or principal.mode != "owner" or not principal.elevated:
            raise AuthError("AUTH.ELEVATION_REQUIRED")
        check_authority()
        return Training(cast(ConversationStore, runtime.store))

    def trace(event: str) -> None:
        cast(TraceService, runtime.traces).emit(new_id(), "training", event, "SUCCEEDED")

    @app.exception_handler(TrainingError)
    async def error(request: Request, exc: TrainingError) -> JSONResponse:
        return JSONResponse({"error": exc.code}, status_code=409)

    @app.get("/training")
    async def status(request: Request) -> dict[str, Any]:
        return await asyncio.to_thread(service(request).status)

    @app.post("/training/configure")
    async def configure(request: Request, value: Enabled) -> dict[str, Any]:
        result = await asyncio.to_thread(service(request).configure, value.enabled)
        trace("experiment_configured")
        return result

    @app.post("/training/example")
    async def example(request: Request, value: Example) -> dict[str, str]:
        result = await asyncio.to_thread(service(request).add, value)
        trace("example_approved")
        return result

    @app.post("/training/remove")
    async def remove(request: Request, value: Identifier) -> dict[str, bool]:
        await asyncio.to_thread(service(request).remove, value.id)
        return {"removed": True}

    @app.post("/training/dataset")
    async def dataset(request: Request) -> dict[str, Any]:
        result = await asyncio.to_thread(service(request).dataset)
        trace("dataset_reviewed")
        return result

    @app.get("/training/recipe")
    async def recipe(request: Request) -> dict[str, str]:
        service(request).required()
        return {
            "filename": "train-adapter.py",
            "script": (Path(__file__).parent / "recipe.txt").read_text(encoding="utf-8"),
            "status": "EXPERIMENTAL_NOT_EXECUTED",
            "environment": "separate Colab/Kaggle GPU environment",
        }

    @app.post("/training/compare")
    async def compare_reports(request: Request, value: Comparison) -> dict[str, Any]:
        service(request).required()
        result = await asyncio.to_thread(assess, value.base, value.candidate, value.target)
        trace("candidate_assessed")
        return result
