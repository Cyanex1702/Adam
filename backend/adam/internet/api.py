import asyncio
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from adam.internet.network import InternetError
from adam.internet.service import (
    URL,
    Approval,
    BrowserCommand,
    Configuration,
    Connection,
    Identifier,
    Internet,
    Preview,
    Search,
)
from adam.security.auth import AuthError
from adam.security.gateway import request_token
from adam.security.policy import Principal
from adam.security.request import check_authority


def install_internet(app: FastAPI, service: Internet) -> None:
    app.state.internet = service

    def owner(request: Request) -> tuple[str, Principal]:
        token = request_token(request)
        principal = app.state.auth.resolve(token)
        if principal.mode != "owner":
            raise AuthError("POLICY.OWNER_REQUIRED")
        check_authority()
        return app.state.auth._hash(token), principal

    @app.exception_handler(InternetError)
    async def error(request: Request, exc: InternetError) -> JSONResponse:
        return JSONResponse({"error": exc.code}, status_code=409)

    @app.get("/internet")
    async def status(request: Request) -> dict[str, Any]:
        key, _ = owner(request)
        return service.status(key)

    @app.post("/internet/configure")
    async def configure(request: Request, value: Configuration) -> dict[str, Any]:
        key, principal = owner(request)
        return await asyncio.to_thread(service.configure, key, value.enabled, principal)

    @app.post("/internet/search")
    async def search(request: Request, value: Search) -> dict[str, Any]:
        key, _ = owner(request)
        return await asyncio.to_thread(service.retrieve, key, value)

    @app.post("/internet/fetch")
    async def fetch(request: Request, value: URL) -> dict[str, Any]:
        key, _ = owner(request)
        return await asyncio.to_thread(service.retrieve, key, value)

    @app.post("/internet/connect")
    async def connect(request: Request, value: Connection) -> dict[str, Any]:
        key, principal = owner(request)
        return await asyncio.to_thread(service.connect, key, value, principal)

    @app.post("/internet/disconnect")
    async def disconnect(request: Request, value: Identifier) -> dict[str, bool]:
        key, _ = owner(request)
        await asyncio.to_thread(service.disconnect, key, value.identifier)
        return {"disconnected": True}

    @app.post("/internet/browser")
    async def browser(request: Request, value: BrowserCommand) -> dict[str, Any]:
        key, _ = owner(request)
        return await asyncio.to_thread(service.browser, key, value)

    @app.post("/internet/preview")
    async def preview(request: Request, value: Preview) -> dict[str, Any]:
        key, _ = owner(request)
        return await asyncio.to_thread(service.preview, key, value)

    @app.post("/internet/approve")
    async def approve(request: Request, value: Approval) -> dict[str, Any]:
        key, principal = owner(request)
        return await asyncio.to_thread(service.approve, key, value, principal)

    @app.post("/internet/execute")
    async def execute(request: Request, value: Identifier) -> dict[str, Any]:
        key, principal = owner(request)
        return await asyncio.to_thread(service.execute, key, value.identifier, principal)

    @app.post("/internet/cancel")
    async def cancel(request: Request, value: Identifier) -> dict[str, bool]:
        key, _ = owner(request)
        await asyncio.to_thread(service.cancel, key, value.identifier)
        return {"cancelled": True}
