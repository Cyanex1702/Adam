import ctypes
import os
import sqlite3
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

from adam.core.config import Settings
from adam.knowledge.retrieval import QueryRequest
from adam.observability.service import TraceService
from adam.security.gateway import RuntimeProxy
from adam.tasks.service import TaskService


def process_memory() -> int | None:
    if os.name != "nt":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("page_faults", ctypes.c_ulong),
            *[
                (name, ctypes.c_size_t)
                for name in [
                    "peak",
                    "working",
                    "peak_pool",
                    "pool",
                    "peak_nonpaged",
                    "nonpaged",
                    "pagefile",
                    "peak_pagefile",
                ]
            ],
        ]

    try:
        counts = Counters()
        counts.cb = ctypes.sizeof(counts)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counts), counts.cb):
            return int(counts.working)
    except (OSError, AttributeError):
        pass
    return None


def install_console(app: FastAPI, runtime: RuntimeProxy, config: Settings) -> None:
    root = Path(__file__).parent / "web"

    @app.get("/developer/evals/scenarios")
    async def scenarios() -> list[str]:
        from adam.evals.security import ATTACKS
        from adam.evals.suite import names

        return [*names(), *ATTACKS]

    @app.post("/developer/evals/replay/{name}")
    async def replay(name: str) -> Any:
        from adam.evals.security import ATTACKS, execute_security
        from adam.evals.suite import execute, names

        if name in ATTACKS:
            return (await execute_security(name, config)).model_dump(mode="json")
        if name not in names():
            return JSONResponse(status_code=404, content={"error": "EVAL.UNKNOWN_SCENARIO"})
        return (await execute(name, config)).model_dump(mode="json")

    def asset(name: str, media_type: str) -> FileResponse:
        return FileResponse(
            root / name,
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self'; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            },
        )

    @app.get("/console", include_in_schema=False)
    async def console() -> FileResponse:
        return asset("index.html", "text/html")

    @app.get("/console.js", include_in_schema=False)
    async def javascript() -> FileResponse:
        return asset("console.js", "text/javascript")

    @app.get("/console.css", include_in_schema=False)
    async def stylesheet() -> FileResponse:
        return asset("console.css", "text/css")

    @app.get("/developer/traces/{identifier}")
    async def trace_detail(identifier: str) -> Any:
        service = cast(TraceService, runtime.traces)
        events = service.list(identifier, 1000)
        if not events:
            return JSONResponse(status_code=404, content={"error": "TRACE.NOT_FOUND"})
        return {
            "trace_id": identifier,
            "events": [item.model_dump() for item in events],
            "error_subsystems": sorted(
                {service.classify(item.error_code) for item in events if item.error_code}
            ),
            "latency_note": "Stage timings overlap; first-token latency is part of generation.",
        }

    @app.get("/developer/health")
    async def dashboard() -> dict[str, object]:
        try:
            with runtime.store.connect() as db:
                database = (
                    "HEALTHY"
                    if db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                    else "FAILED"
                )
        except sqlite3.Error:
            database = "FAILED"
        model = await runtime.provider.health_check()
        trace = cast(TraceService, runtime.traces)
        trace_status = "DISABLED" if trace.config.level == "OFF" else "HEALTHY"
        try:
            trace.list(limit=1)
        except (sqlite3.Error, OSError, ValueError):
            trace_status = "FAILED"
        return {
            "subsystems": {
                "storage": database,
                "model": model.status,
                "identity": "HEALTHY",
                "policy": "HEALTHY",
                "traces": trace_status,
                "tools": "HEALTHY",
                "knowledge": "HEALTHY" if config.knowledge.enabled else "DISABLED",
            },
            "model": runtime.provider.get_capabilities().model_dump(),
            "resources": {
                "process_ram_bytes": process_memory(),
                "cpu_count": os.cpu_count(),
                "vram_bytes": None,
                "vram_status": "UNAVAILABLE",
            },
            "compute": runtime.compute.observe(),
            "capability_envelope": runtime.compute.envelope(),
            "tracing": trace.config.model_dump(),
            "knowledge_note": "Configured availability; inspect retrieval diagnostics separately.",
        }

    @app.get("/developer/memory")
    async def memory_inspector(
        query: str = Query(default="", max_length=2048),
    ) -> list[dict[str, object]]:
        return [
            {
                "memory_id": item.memory_id,
                "status": item.status,
                "tier": item.tier,
                "sensitivity": item.privacy,
                "epistemic_status": item.epistemic_status,
            }
            for item in runtime.memories.search(query)
        ]

    @app.get("/developer/knowledge")
    async def knowledge_inspector(
        query: str = Query(min_length=1, max_length=2000),
        namespace: str = Query(default="default", pattern=r"^[\w-]{1,64}$"),
    ) -> dict[str, object]:
        import asyncio

        result = await asyncio.to_thread(
            runtime.retrieval.search, QueryRequest(query=query, namespace=namespace)
        )
        return {
            "mode": result.mode,
            "diagnostic": result.diagnostic,
            "revision": result.revision,
            "evidence": [
                {
                    "chunk_id": item.chunk.chunk_id,
                    "source_id": item.source.source_id,
                    "rank_score": item.rank_score,
                    "keyword_score": item.keyword_score,
                    "semantic_score": item.semantic_score,
                }
                for item in result.evidence
            ],
        }

    @app.get("/developer/tasks/{identifier}")
    async def graph(identifier: str) -> dict[str, object]:
        task = cast(TaskService, runtime.tasks).get(identifier)
        return {
            "task_id": task.task_id,
            "status": task.status,
            "error_code": task.error_code,
            "elapsed_seconds": task.elapsed_seconds,
            "steps": [
                {
                    "step_id": step.step_id,
                    "dependencies": step.dependencies,
                    "tool": step.call.name,
                    "status": step.status,
                    "action_id": step.action_id,
                    "attempts": step.attempts,
                }
                for step in task.plan.steps
            ],
        }
