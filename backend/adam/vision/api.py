import asyncio
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from adam.security.auth import AuthError
from adam.security.gateway import request_token
from adam.security.request import REMOTE_DEVICE, check_authority
from adam.vision.images import VisionError
from adam.vision.service import Analysis, Capture, Configuration, Vision


def install_vision(app: FastAPI, service: Vision) -> None:
    app.state.vision = service

    @app.exception_handler(AuthError)
    async def auth_error(request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            {"error": exc.code}, status_code=401 if exc.code == "AUTH.REQUIRED" else 403
        )

    def owner(request: Request, elevated: bool = False) -> str:
        token = request_token(request)
        principal = app.state.auth.resolve(token)
        if principal.mode != "owner" or REMOTE_DEVICE.get():
            raise AuthError("POLICY.OWNER_REQUIRED")
        if elevated and not principal.elevated:
            raise AuthError("AUTH.ELEVATION_REQUIRED")
        check_authority()
        return str(app.state.auth._hash(token))

    @app.exception_handler(VisionError)
    async def error(request: Request, exc: VisionError) -> JSONResponse:
        return JSONResponse({"error": exc.code}, status_code=409)

    @app.get("/vision")
    async def status(request: Request) -> dict[str, Any]:
        key = owner(request)
        return await asyncio.to_thread(service.status, key)

    @app.post("/vision/configure")
    async def configure(request: Request, value: Configuration) -> dict[str, Any]:
        key = owner(request, elevated=value.enabled)
        return await asyncio.to_thread(service.configure, key, value)

    @app.post("/vision/analyze")
    async def analyze(request: Request, value: Analysis) -> dict[str, Any]:
        key = owner(request)
        return await asyncio.to_thread(service.analyze, key, value)

    @app.post("/vision/capture")
    async def capture(request: Request, value: Capture) -> dict[str, Any]:
        key = owner(request, elevated=True)
        return await asyncio.to_thread(service.analyze, key, value)

    @app.get("/vision/windows")
    async def windows(request: Request) -> dict[str, Any]:
        key = owner(request, elevated=True)
        return await asyncio.to_thread(service.list_windows, key)
