import asyncio
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from adam.computer.provider import ComputerError
from adam.computer.service import Computer, PlanRequest
from adam.core.contracts import Contract
from adam.security.auth import AuthError
from adam.security.gateway import request_token
from adam.security.request import REMOTE_DEVICE, check_authority
from adam.vision.service import Configuration


class Identifier(Contract):
    id: str = Field(pattern=r"^[a-f0-9-]{36}$")


class Approval(Identifier):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Execution(Identifier):
    dry_run: bool = False


def install_computer(app: FastAPI, service: Computer) -> None:
    app.state.computer = service

    def owner(request: Request, elevated: bool = True) -> str:
        token = request_token(request)
        principal = app.state.auth.resolve(token)
        if principal.mode != "owner" or REMOTE_DEVICE.get():
            raise AuthError("POLICY.OWNER_REQUIRED")
        if elevated and not principal.elevated:
            raise AuthError("AUTH.ELEVATION_REQUIRED")
        check_authority()
        return str(app.state.auth._hash(token))

    @app.exception_handler(ComputerError)
    async def error(request: Request, exc: ComputerError) -> JSONResponse:
        return JSONResponse({"error": exc.code}, status_code=409)

    @app.get("/computer")
    async def status(request: Request) -> dict[str, Any]:
        return service.status(owner(request, False))

    @app.post("/computer/configure")
    async def configure(request: Request, value: Configuration) -> dict[str, Any]:
        key = owner(request, value.enabled)
        return await asyncio.to_thread(service.configure, key, value)

    @app.get("/computer/windows")
    async def windows(request: Request) -> dict[str, Any]:
        return await asyncio.to_thread(service.list_windows, owner(request))

    @app.post("/computer/observe")
    async def observe(request: Request, value: Identifier) -> dict[str, Any]:
        return await asyncio.to_thread(service.observe, owner(request), value.id)

    @app.post("/computer/plan")
    async def plan(request: Request, value: PlanRequest) -> dict[str, Any]:
        return service.plan(owner(request), value)

    @app.post("/computer/approve")
    async def approve(request: Request, value: Approval) -> dict[str, Any]:
        return service.approve(owner(request), value.id, value.digest)

    @app.post("/computer/execute")
    async def execute(request: Request, value: Execution) -> dict[str, Any]:
        return await asyncio.to_thread(service.execute, owner(request), value.id, value.dry_run)
