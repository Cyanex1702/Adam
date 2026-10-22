import asyncio
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from adam.core.contracts import SessionId
from adam.operations.service import Identifier, Operations, OperationsError, Preferences, Schedule
from adam.security.auth import AuthError
from adam.security.gateway import request_token
from adam.security.request import check_authority


def install_operations(app: FastAPI, service: Operations | None) -> None:
    app.state.operations = service

    def owner(request: Request) -> None:
        if app.state.auth.resolve(request_token(request)).mode != "owner":
            raise AuthError("POLICY.OWNER_REQUIRED")
        check_authority()

    def required() -> Operations:
        if service is None:
            raise OperationsError("OPERATIONS.STORE_UNAVAILABLE")
        return service

    @app.exception_handler(OperationsError)
    async def error(request: Request, exc: OperationsError) -> JSONResponse:
        return JSONResponse({"error": exc.code}, status_code=409)

    @app.get("/operations")
    async def status(request: Request) -> dict[str, Any]:
        owner(request)
        return await asyncio.to_thread(required().status)

    @app.post("/operations/schedule")
    async def schedule(request: Request, value: Schedule) -> dict[str, Any]:
        owner(request)
        if value.session_id and not app.state.runtime.store.get(SessionId(str(value.session_id))):
            raise OperationsError("OPERATIONS.SESSION_UNAVAILABLE")
        return await asyncio.to_thread(required().create, value)

    @app.post("/operations/cancel")
    async def cancel(request: Request, value: Identifier) -> dict[str, bool]:
        owner(request)
        await asyncio.to_thread(required().cancel, str(value.identifier))
        return {"cancelled": True}

    @app.post("/operations/preferences")
    async def preferences(request: Request, value: Preferences) -> dict[str, Any]:
        owner(request)
        return await asyncio.to_thread(required().configure, value)

    @app.get("/operations/inbox")
    async def inbox(request: Request) -> list[dict[str, Any]]:
        owner(request)
        mesh = getattr(app.state, "mesh", None)
        primary = (lambda session: mesh.store.primary(session)["primary"]) if mesh else None
        return await asyncio.to_thread(required().inbox, "desktop", primary)

    @app.post("/operations/acknowledge")
    async def acknowledge(request: Request, value: Identifier) -> dict[str, bool]:
        owner(request)
        await asyncio.to_thread(required().acknowledge, str(value.identifier))
        return {"acknowledged": True}
