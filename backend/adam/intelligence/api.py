import asyncio
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from adam.core.contracts import Contract, new_id
from adam.intelligence.service import Goal, Intelligence, Link, PersonalError
from adam.memory.service import MemoryService
from adam.observability.service import TraceService
from adam.security.auth import AuthError
from adam.security.gateway import RuntimeProxy, request_token
from adam.security.request import REMOTE_DEVICE, check_authority


class Search(Contract):
    query: str = Field(default="", max_length=1000)
    historical: bool = False
    start: datetime | None = None
    end: datetime | None = None
    as_of: datetime | None = None


class Remove(Contract):
    kind: Literal["link", "goal"]
    id: str = Field(pattern=r"^[a-f0-9-]{36}$")


def install_intelligence(app: FastAPI) -> None:
    runtime = RuntimeProxy()

    def service(request: Request, *, write: bool = False) -> Intelligence:
        principal = app.state.auth.resolve(request_token(request))
        if (
            REMOTE_DEVICE.get()
            or principal.mode == "guest"
            or (write and principal.mode not in {"owner", "demo"})
        ):
            raise AuthError("POLICY.OWNER_OR_DEMO_REQUIRED")
        check_authority()
        return Intelligence(cast(MemoryService, runtime.memories))

    def trace(event: str) -> None:
        cast(TraceService, runtime.traces).emit(new_id(), "personal", event, "SUCCEEDED")

    @app.exception_handler(PersonalError)
    async def error(request: Request, exc: PersonalError) -> JSONResponse:
        return JSONResponse({"error": exc.code}, status_code=409)

    @app.get("/personal")
    async def status(request: Request) -> dict[str, Any]:
        current = service(request)
        return {
            "goals": await asyncio.to_thread(current.goals),
            "briefing": await asyncio.to_thread(current.briefing),
        }

    @app.post("/personal/graph")
    async def graph(request: Request, value: Search) -> dict[str, Any]:
        return await asyncio.to_thread(
            service(request).graph, value.query, historical=value.historical
        )

    @app.post("/personal/timeline")
    async def timeline(request: Request, value: Search) -> dict[str, Any]:
        return await asyncio.to_thread(
            service(request).timeline, value.query, value.start, value.end, value.as_of
        )

    @app.get("/personal/evidence")
    async def evidence(
        request: Request, id: str = Query(pattern=r"^[a-f0-9-]{36}$")
    ) -> dict[str, Any]:
        return (await asyncio.to_thread(service(request).evidence, id, historical=True)).model_dump(
            mode="json"
        )

    @app.post("/personal/link")
    async def link(request: Request, value: Link) -> dict[str, Any]:
        result = await asyncio.to_thread(service(request, write=True).link, value)
        trace("link_reviewed")
        return result

    @app.post("/personal/goal")
    async def goal(request: Request, value: Goal) -> dict[str, Any]:
        result = await asyncio.to_thread(service(request, write=True).save_goal, value)
        trace("goal_updated")
        return result

    @app.post("/personal/remove")
    async def remove(request: Request, value: Remove) -> dict[str, bool]:
        await asyncio.to_thread(service(request, write=True).delete, value.kind, value.id)
        trace("structure_removed")
        return {"removed": True}
