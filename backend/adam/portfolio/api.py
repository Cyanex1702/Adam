import asyncio
from typing import Any, cast
from weakref import WeakValueDictionary

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from adam.core.contracts import new_id
from adam.observability.service import TraceService
from adam.portfolio.service import DemoTool, PortfolioError, benchmarks, demo_tool
from adam.security.auth import AuthError
from adam.security.gateway import CURRENT, RuntimeProxy, request_token
from adam.security.request import REMOTE_DEVICE, check_authority


def install_portfolio(app: FastAPI) -> None:
    runtime = RuntimeProxy()
    demo_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    @app.exception_handler(PortfolioError)
    async def error(request: Request, exc: PortfolioError) -> JSONResponse:
        return JSONResponse({"error": exc.code}, status_code=409)

    @app.get("/portfolio")
    async def status() -> dict[str, Any]:
        check_authority()
        mode = CURRENT.get().principal.mode
        return {
            "mode": mode,
            "synthetic": mode == "demo",
            "training": "EXPERIMENTAL_DEFERRED",
            "features": [
                "chat",
                "memory",
                "sample RAG",
                "personal structures",
                "safe demo note tool",
            ],
            "walkthrough": [
                "Ask: /show memory demo editor",
                "Ask: /ask What is Cedar launch command?",
                "Inspect personal structures and current versus historical evidence.",
                "Write and undo a fictional note in the isolated demo sandbox.",
            ],
            "limits": [
                "Standard Win32 controls only for computer actions",
                "No general scene model bundled",
                "Human desktop, voice and Android acceptance remain pending",
                "No validated fine-tuned adapter",
            ],
        }

    @app.get("/portfolio/benchmarks")
    async def dashboard() -> dict[str, Any]:
        check_authority()
        return await asyncio.to_thread(benchmarks)

    @app.post("/portfolio/demo-tool")
    async def tool(request: Request, value: DemoTool) -> dict[str, Any]:
        principal = app.state.auth.resolve(request_token(request))
        if principal.mode != "demo" or REMOTE_DEVICE.get():
            raise AuthError("POLICY.DEMO_ONLY")
        check_authority()
        key = principal.profile_id
        lock = demo_locks.setdefault(key, asyncio.Lock())
        async with lock:
            result = await asyncio.to_thread(demo_tool, runtime.settings.data_dir, value)
        cast(TraceService, runtime.traces).emit(new_id(), "portfolio", "demo_tool", "SUCCEEDED")
        return result
