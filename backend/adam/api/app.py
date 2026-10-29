import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal, cast

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import SecretStr, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from adam import APP_VERSION
from adam.compute.api import install_compute
from adam.computer.api import install_computer
from adam.computer.service import Computer
from adam.core.config import Settings, load_settings, resolve_catalog_settings
from adam.core.contracts import Contract, ErrorEnvelope, EventEnvelope, SessionId, TraceId, new_id
from adam.core.migrations import migrate
from adam.core.runtime import ChatRequest
from adam.core.working import WorkingState
from adam.distribution.api import install_distribution
from adam.intelligence.api import install_intelligence
from adam.internet.api import install_internet
from adam.internet.service import Internet
from adam.knowledge.contracts import SourceRequest
from adam.knowledge.embedding import EmbeddingUnavailable
from adam.knowledge.parsing import IngestionError
from adam.knowledge.retrieval import QueryRequest
from adam.models.base import ModelProvider
from adam.models.llama_cpp import LlamaCppProvider
from adam.observability.api import install_console
from adam.observability.service import TraceService
from adam.operations.api import install_operations
from adam.operations.service import Operations
from adam.portfolio.api import install_portfolio
from adam.resilience.api import install_maintenance
from adam.security.auth import AuthError, AuthManager
from adam.security.gateway import AuthBoundary, RuntimePool, RuntimeProxy, request_token
from adam.security.policy import ResourcePolicy, decide
from adam.security.vault import Vault, VaultError
from adam.tasks.service import Plan, Task, TaskService
from adam.tools.contracts import ToolCall
from adam.tools.registry import ToolError
from adam.tools.service import Action, ActionService
from adam.training.api import install_training
from adam.vision.api import install_vision
from adam.vision.service import Vision


def create_app(settings: Settings | None = None, provider: ModelProvider | None = None) -> FastAPI:
    from adam.resilience.recovery import inspect, recovery_app

    try:
        config = resolve_catalog_settings(settings) if settings else load_settings()
    except (ValueError, OSError):
        from adam.core.config import resolve_data_dir

        return recovery_app(Settings(data_dir=resolve_data_dir()), ["CONFIG.INVALID"])

    if inspect(config)["mode"] != "HEALTHY":
        return recovery_app(config)
    pool = RuntimePool(config, provider or LlamaCppProvider(config.model))
    auth = AuthManager(config.data_dir)
    vault = Vault(config.data_dir, config.vault_backend, config.vault_enabled)
    runtime = RuntimeProxy()
    try:
        operations: Operations | None = Operations(config.data_dir)
    except (sqlite3.Error, OSError, ValueError):
        operations = None  # Preserve damaged optional store; local chat remains usable.

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        migrate(config.data_dir / "runtime.sqlite3")

        # The login/recovery UI must remain usable while model loading is slow,
        # blocked by resources, or waiting for an external server.
        startup_reserved = asyncio.Event()

        async def watch_model() -> None:
            # No await between signalling and entering startup's load reservation.
            # Requests may enter the app only after that reservation has begun.
            startup_reserved.set()
            await models_controller.startup()
            manager = models_controller.manager
            while True:
                await asyncio.sleep(5)
                if manager.operation_active or manager.turns:
                    continue
                from adam.compute.owned import OwnedLlamaProvider

                if not isinstance(manager.delegate, OwnedLlamaProvider) and manager.error in {
                    "MODEL.UNAVAILABLE",
                    "MODEL.CONTEXT_MISMATCH",
                    "MODEL.IDENTITY_MISMATCH",
                }:
                    health = await manager.delegate.health_check()
                    manager.last_health = health
                    if health.status == "HEALTHY":
                        manager.error, manager.state = None, "LOADED"
                else:
                    await manager.health_check()

        model_startup = asyncio.create_task(watch_model())
        await startup_reserved.wait()
        await pool.owner.consolidation.start(config.consolidation_interval_seconds)
        if operations:
            await operations.start()
        try:
            yield
        finally:
            model_startup.cancel()
            await asyncio.gather(model_startup, return_exceptions=True)
            if hasattr(app.state, "setup"):
                app.state.setup.cancel.set()
            if operations:
                await operations.stop()
            await pool.close()

    app = FastAPI(
        title="ADAM Alpha",
        version=APP_VERSION,
        lifespan=lifespan,
    )
    app.state.runtime = pool.owner
    app.state.auth = auth
    app.state.vault = vault
    install_operations(app, operations)
    install_internet(app, Internet(pool.owner.traces))
    install_computer(app, Computer(pool.owner.traces))
    install_distribution(app, config)
    install_intelligence(app)
    install_training(app)
    install_portfolio(app)
    install_vision(app, Vision(pool.owner.traces))

    def authenticated_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
            schema.setdefault("components", {}).setdefault("securitySchemes", {})["Bearer"] = {
                "type": "http",
                "scheme": "bearer",
            }
            for path, operations in schema["paths"].items():
                if path not in {"/health", "/auth/login", "/auth/session"}:
                    for operation in operations.values():
                        if isinstance(operation, dict):
                            operation["security"] = [{"Bearer": []}]
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = authenticated_openapi  # type: ignore[method-assign]
    app.add_middleware(AuthBoundary, auth=auth, pool=pool)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])
    install_console(app, runtime, config)
    install_maintenance(app, config)
    models_controller = install_compute(app, pool.provider)

    @app.get("/developer/hardware")
    async def hardware_profile(benchmark: bool = False) -> dict[str, Any]:
        from adam.compute.hardware import profile

        return await asyncio.to_thread(profile, config.data_dir, benchmark=benchmark)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError) -> JSONResponse:
        error = ErrorEnvelope(
            code="INPUT.INVALID", message="Invalid request fields.", trace_id=TraceId(new_id())
        )
        return JSONResponse(status_code=422, content={"error": error.model_dump(mode="json")})

    @app.exception_handler(VaultError)
    async def unavailable_vault(request: Request, exc: VaultError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"error": exc.code})

    @app.get("/health")
    async def health() -> dict[str, Any]:
        model = await pool.provider.health_check()
        return {
            "status": model.status,
            "model": model.model_dump(),
            "version": APP_VERSION,
        }

    @app.exception_handler(ToolError)
    async def tool_error(request: Request, exc: ToolError) -> JSONResponse:
        trace_id = new_id()
        runtime.traces.emit(
            trace_id, TraceService.classify(exc.code), "request", "FAILED", error_code=exc.code
        )
        return JSONResponse(status_code=409, content={"error": exc.code, "trace_id": trace_id})

    class Approval(Contract):
        digest: str
        allow: bool = True

    @app.get("/tools")
    async def tools() -> dict[str, object]:
        return {
            "scope": str(runtime.actions.scope.root),
            "tools": [item.model_dump() for item in runtime.actions.registry.list()],
        }

    @app.post("/tools/preview")
    async def preview_tool(request: Request, body: ToolCall) -> Action:
        return await asyncio.to_thread(
            runtime.actions.preview, body, auth.resolve(request_token(request))
        )

    @app.get("/actions")
    async def actions() -> list[Action]:
        return cast(ActionService, runtime.actions).list()

    @app.get("/actions/{identifier}")
    async def action(identifier: str) -> Action:
        return cast(ActionService, runtime.actions).get(identifier)

    @app.post("/actions/{identifier}/approve")
    async def approve_action(request: Request, identifier: str, body: Approval) -> Action:
        return await asyncio.to_thread(
            runtime.actions.approve,
            identifier,
            body.digest,
            auth.resolve(request_token(request)),
            body.allow,
        )

    @app.post("/actions/{identifier}/execute")
    async def execute_action(request: Request, identifier: str) -> Action:
        return await asyncio.to_thread(
            runtime.actions.execute, identifier, auth.resolve(request_token(request))
        )

    @app.post("/actions/{identifier}/undo-preview")
    async def undo_action(request: Request, identifier: str) -> Action:
        return await asyncio.to_thread(
            runtime.actions.undo, identifier, auth.resolve(request_token(request))
        )

    class Goal(Contract):
        goal: str

    @app.get("/tasks")
    async def tasks() -> list[Task]:
        return cast(TaskService, runtime.tasks).list()

    @app.post("/tasks")
    async def create_task(request: Request, body: Plan) -> Task:
        return await asyncio.to_thread(
            runtime.tasks.create, body, auth.resolve(request_token(request))
        )

    @app.post("/tasks/plan")
    async def plan_task(request: Request, body: Goal) -> Task:
        principal = auth.resolve(request_token(request))
        runtime.actions.permission(principal)
        plan = await asyncio.to_thread(runtime.tasks.planner.from_goal, body.goal)
        return await asyncio.to_thread(runtime.tasks.create, plan, principal)

    @app.get("/tasks/{identifier}")
    async def get_task(identifier: str) -> Task:
        return cast(TaskService, runtime.tasks).get(identifier)

    @app.post("/tasks/{identifier}/approve")
    async def approve_task(request: Request, identifier: str, body: Approval) -> Task:
        if not body.allow:
            return await asyncio.to_thread(
                runtime.tasks.cancel, identifier, auth.resolve(request_token(request))
            )
        return await asyncio.to_thread(
            runtime.tasks.approve, identifier, body.digest, auth.resolve(request_token(request))
        )

    @app.post("/tasks/{identifier}/run")
    async def run_task(request: Request, identifier: str) -> Task:
        return await asyncio.to_thread(
            runtime.tasks.run,
            identifier,
            auth.resolve(request_token(request)),
            lambda: auth.resolve(request_token(request)),
        )

    @app.post("/tasks/{identifier}/cancel")
    async def cancel_task(request: Request, identifier: str) -> Task:
        return await asyncio.to_thread(
            runtime.tasks.cancel, identifier, auth.resolve(request_token(request))
        )

    @app.post("/tasks/{identifier}/replan")
    async def replan_task(request: Request, identifier: str, body: Plan) -> Task:
        return await asyncio.to_thread(
            runtime.tasks.replan, identifier, body, auth.resolve(request_token(request))
        )

    class Login(Contract):
        password: SecretStr

    class Anonymous(Contract):
        mode: Literal["guest", "demo"] = "demo"

    class VaultUnlock(Contract):
        password: SecretStr = SecretStr("")

    class VaultPut(Contract):
        purpose: str
        value: SecretStr

    @app.get("/vault/status")
    async def vault_status(request: Request) -> dict[str, object]:
        return vault.status(auth.resolve(request_token(request)))

    @app.post("/vault/unlock")
    async def vault_unlock(request: Request, body: VaultUnlock) -> dict[str, object]:
        principal = auth.resolve(request_token(request))
        await asyncio.to_thread(vault.unlock, principal, body.password.get_secret_value())
        return vault.status(principal)

    @app.post("/vault/lock")
    async def vault_lock(request: Request) -> dict[str, object]:
        principal = auth.resolve(request_token(request))
        vault.lock_vault(principal)
        return vault.status(principal)

    @app.get("/vault/handles")
    async def vault_handles(request: Request) -> list[dict[str, str]]:
        return vault.list_handles(auth.resolve(request_token(request)))

    @app.post("/vault/handles")
    async def vault_put(request: Request, body: VaultPut) -> dict[str, str]:
        handle = await asyncio.to_thread(
            vault.put,
            auth.resolve(request_token(request)),
            body.purpose,
            body.value.get_secret_value(),
        )
        return {"handle": handle, "sensitivity": "NEVER_LOG"}

    @app.delete("/vault/handles/{identifier}")
    async def vault_delete(request: Request, identifier: str) -> dict[str, bool]:
        return {
            "deleted": vault.delete(auth.resolve(request_token(request)), "secret://" + identifier)
        }

    class Switch(Contract):
        mode: Literal["owner", "guest", "demo"]
        password: SecretStr | None = None

    def grant(token: str) -> JSONResponse:
        principal = auth.resolve(token)
        response = JSONResponse(
            content={
                "token": token,
                "mode": principal.mode,
                "expires_in_seconds": 1800,
                "developer": principal.elevated,
            }
        )
        response.set_cookie("adam_session", token, httponly=True, samesite="strict", max_age=1800)
        return response

    @app.post("/auth/login")
    async def login(request: Login) -> JSONResponse:
        try:
            return grant(
                await asyncio.to_thread(auth.issue, "owner", request.password.get_secret_value())
            )
        except AuthError as exc:
            return JSONResponse(
                status_code=429 if exc.code == "AUTH.RATE_LIMITED" else 403,
                content={"error": exc.code},
            )

    @app.post("/auth/session")
    async def anonymous(request: Anonymous) -> JSONResponse:
        try:
            return grant(auth.issue(request.mode))
        except AuthError as exc:
            return JSONResponse(status_code=429, content={"error": exc.code})

    @app.get("/auth/status")
    async def auth_status(request: Request) -> dict[str, object]:
        principal = auth.resolve(request_token(request))
        return {
            "mode": principal.mode,
            "person_id": principal.person_id,
            "developer": principal.elevated,
            "profile": principal.profile_id if principal.mode != "owner" else "owner",
        }

    @app.post("/auth/elevate")
    async def elevate(request: Request, body: Login) -> JSONResponse:
        try:
            await asyncio.to_thread(
                auth.elevate, request_token(request), body.password.get_secret_value()
            )
            return JSONResponse(content={"developer": True, "expires_in_seconds": 300})
        except AuthError as exc:
            return JSONResponse(status_code=403, content={"error": exc.code})

    @app.post("/auth/logout")
    async def logout(request: Request) -> JSONResponse:
        auth.revoke(request_token(request))
        response = JSONResponse(content={"logged_out": True})
        response.delete_cookie("adam_session")
        return response

    @app.post("/auth/switch")
    async def switch(request: Request, body: Switch) -> JSONResponse:
        try:
            token = await asyncio.to_thread(
                auth.issue, body.mode, body.password.get_secret_value() if body.password else None
            )
            auth.revoke(request_token(request))
            return grant(token)
        except AuthError as exc:
            return JSONResponse(status_code=403, content={"error": exc.code})

    @app.post("/developer/policy")
    async def explain_policy(request: Request, resource: ResourcePolicy) -> dict[str, object]:
        return decide(auth.resolve(request_token(request)), resource).model_dump()

    @app.get("/developer/traces")
    async def traces() -> list[dict[str, Any]]:
        return [point.model_dump() for point in cast(TraceService, runtime.traces).list()]

    @app.get("/models")
    async def models() -> list[dict[str, Any]]:
        return [card.model_dump() for card in runtime.registry.cards()]

    @app.get("/identity")
    async def identity() -> dict[str, object]:
        health = await runtime.provider.health_check()
        result = runtime.identity.describe(
            runtime.provider.get_capabilities(),
            config.features.text,
            health.status == "HEALTHY",
            config.knowledge.enabled,
            tools_enabled=True,
            voice_enabled=config.features.voice,
            speaker_enabled=config.features.speaker_id,
            mobile_enabled=config.features.mobile_mesh,
        )
        result["mode"] = runtime.principal.mode
        result["compute_capabilities"] = runtime.compute.envelope()
        return result  # type: ignore[no-any-return]

    @app.post("/chat")
    async def chat(request: ChatRequest) -> JSONResponse:
        result = await runtime.chat(request)
        return JSONResponse(
            status_code=503 if result.event_type == "agent.error" else 200,
            content=result.model_dump(mode="json"),
        )

    @app.delete("/sessions/{session_id}")
    async def close_session(session_id: str) -> dict[str, bool]:
        return {"closed": runtime.sessions.close(SessionId(session_id))}

    @app.get("/sessions")
    async def sessions() -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], runtime.store.list_sessions())

    @app.get("/sessions/{session_id}/history")
    async def history(
        session_id: str, limit: int = 100, before: int | None = None
    ) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            runtime.store.history(SessionId(session_id), max(1, min(limit, 500)), before),
        )

    @app.post("/sessions/{session_id}/resume")
    async def resume(session_id: str) -> dict[str, bool]:
        return {"resumed": runtime.sessions.reopen(SessionId(session_id))}

    @app.get("/sessions/{session_id}/working")
    async def working(session_id: str) -> JSONResponse:
        row = runtime.store.get(SessionId(session_id))
        if not row:
            return JSONResponse(status_code=404, content={"error": "SESSION.NOT_FOUND"})
        return JSONResponse(
            content={
                "state": runtime.store.working(SessionId(session_id)).model_dump(),
                "summary": row["summary"],
                "context_budget": row["context_budget"],
            }
        )

    @app.put("/sessions/{session_id}/working")
    async def update_working(session_id: str, state: WorkingState) -> JSONResponse:
        try:
            runtime.store.set_working(SessionId(session_id), state)
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "INPUT.INVALID"})
        return JSONResponse(content={"updated": True})

    @app.get("/memory")
    async def memory(
        query: str = "", historical: bool = False, archived: bool = False
    ) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json")
            for item in runtime.memories.search(
                query[:2000], historical=historical, archived=archived
            )
        ]

    @app.delete("/memory/{memory_id}")
    async def forget_memory(memory_id: str) -> JSONResponse:
        result = await runtime.chat(ChatRequest(text="/forget " + memory_id))
        return JSONResponse(
            status_code=400 if result.event_type == "agent.error" else 200,
            content=result.model_dump(mode="json"),
        )

    @app.get("/memory/candidates")
    async def candidates() -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in runtime.consolidation.candidates()]

    @app.post("/knowledge/sources")
    async def ingest_source(request: SourceRequest) -> JSONResponse:
        try:
            source = await asyncio.to_thread(runtime.knowledge.ingest, request)
            return JSONResponse(content=source.model_dump(mode="json"))
        except IngestionError as exc:
            return JSONResponse(
                status_code=400, content={"error": "RAG.INGEST_REJECTED", "message": str(exc)}
            )

    @app.get("/knowledge/sources")
    async def sources(namespace: str | None = None) -> list[dict[str, Any]]:
        return [source.model_dump(mode="json") for source in runtime.knowledge.sources(namespace)]

    @app.post("/knowledge/refresh")
    async def refresh(namespace: str | None = None) -> list[dict[str, Any]]:
        sources = await asyncio.to_thread(runtime.knowledge.refresh, namespace)
        return [source.model_dump(mode="json") for source in sources]

    @app.post("/knowledge/retrieve")
    async def retrieve(request: QueryRequest) -> JSONResponse:
        try:
            result = await asyncio.to_thread(runtime.retrieval.search, request)
            return JSONResponse(content=result.model_dump(mode="json"))
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "RAG.QUERY_REJECTED"})

    @app.post("/knowledge/reindex")
    async def reindex() -> JSONResponse:
        try:
            return JSONResponse(content=await pool.provider.background(runtime.retrieval.reindex))
        except EmbeddingUnavailable as exc:
            return JSONResponse(
                status_code=503, content={"error": "RAG.INDEX_UNAVAILABLE", "message": str(exc)}
            )

    @app.post("/knowledge/answer")
    async def answer_sources(request: QueryRequest) -> JSONResponse:
        try:
            result = await asyncio.to_thread(runtime.grounding.answer, request)
            return JSONResponse(content=result.model_dump(mode="json"))
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "RAG.QUERY_REJECTED"})

    @app.websocket("/ws/chat")
    async def websocket_chat(socket: WebSocket) -> None:
        origin = socket.headers.get("origin")
        if origin and origin not in {"http://localhost:8765", "http://127.0.0.1:8765"}:
            await socket.close(code=1008)
            return
        await socket.accept()
        try:
            while True:
                try:
                    request = ChatRequest.model_validate(await socket.receive_json())
                except (ValidationError, ValueError):
                    error = ErrorEnvelope(
                        code="INPUT.INVALID",
                        message="Invalid message fields.",
                        trace_id=TraceId(new_id()),
                    )
                    await socket.send_json(
                        EventEnvelope(
                            event_type="agent.error",
                            trace_id=error.trace_id,
                            payload={"error": error.model_dump()},
                        ).model_dump(mode="json")
                    )
                    continue
                stream = runtime.stream(request)
                try:
                    async for event in stream:
                        await socket.send_json(event.model_dump(mode="json"))
                finally:
                    await stream.aclose()
        except WebSocketDisconnect:
            pass

    return app
