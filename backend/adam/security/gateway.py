import asyncio
from collections import OrderedDict
from contextvars import ContextVar
from typing import Any

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from adam.compute.resources import ManagedProvider
from adam.core.config import Settings
from adam.core.contracts import SessionId, TraceId, new_id
from adam.core.runtime import Runtime
from adam.knowledge.contracts import SourcePolicy, SourceRequest
from adam.memory.service import MemoryCommand
from adam.models.base import ModelProvider
from adam.security.auth import AuthError, AuthManager
from adam.security.policy import Principal
from adam.security.request import AUTHORITY

CURRENT: ContextVar[Runtime] = ContextVar("adam_request_runtime")


class RuntimeProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(CURRENT.get(), name)


def request_token(connection: HTTPConnection) -> str:
    authorization = connection.headers.get("authorization", "")
    if authorization:
        if not authorization.startswith("Bearer "):
            raise AuthError("AUTH.REQUIRED")
        return authorization[7:]
    return connection.cookies.get("adam_session", "")


class RuntimePool:
    def __init__(self, settings: Settings, provider: ModelProvider) -> None:
        self.settings = settings
        self.provider = (
            provider
            if isinstance(provider, ManagedProvider)
            else ManagedProvider(provider, settings)
        )
        self.owner = Runtime(settings, self.provider)
        self.profiles: OrderedDict[str, Runtime] = OrderedDict()
        self.lock = asyncio.Lock()

    async def get(self, principal: Principal) -> Runtime:
        if principal.mode == "owner":
            return self.owner
        async with self.lock:
            key = principal.mode + ":" + principal.profile_id
            if key in self.profiles:
                self.profiles.move_to_end(key)
                return self.profiles[key]
            if len(self.profiles) >= 16:
                idle = next(
                    (
                        name
                        for name, runtime in self.profiles.items()
                        if not any(session.busy for session in runtime.sessions.sessions.values())
                    ),
                    None,
                )
                if idle is None:
                    raise AuthError("AUTH.PROFILE_CAPACITY")
                old = self.profiles.pop(idle)
                await old.consolidation.stop()
                await asyncio.to_thread(old.retrieval.close)
            runtime = Runtime(self.settings, self.provider, principal)
            if principal.mode == "demo":
                await asyncio.to_thread(seed_demo, runtime)
            self.profiles[key] = runtime
            return runtime

    async def close(self) -> None:
        for runtime in [self.owner, *self.profiles.values()]:
            await runtime.consolidation.stop()
            await asyncio.to_thread(runtime.retrieval.close)
        await self.provider.unload()


def seed_demo(runtime: Runtime) -> None:
    """Only generated fictional samples; never copy from owner files or databases."""
    folder = runtime.settings.data_dir / "samples"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "fictional-cedar.md"
    if not path.exists():
        path.write_text(
            "Fictional Cedar launch command: cedar serve --port 9123\n"
            "Fictional Orchid backups run each Friday.\n",
            encoding="utf-8",
            newline="\n",
        )
    runtime.knowledge.ingest(
        SourceRequest(
            path=str(path),
            namespace="demo",
            policy=SourcePolicy(
                profile="demo",
                allowed_audiences=["demo"],
                subjects=["demo"],
                disclosure_owner="demo",
                source_actor="synthetic_fixture",
            ),
        )
    )
    if not runtime.memories.search("demo editor"):
        sid = SessionId(new_id())
        runtime.store.create(sid)
        with runtime.store.connect() as db:
            runtime.memories.execute(
                db,
                MemoryCommand("remember", "preference demo editor = Example Studio"),
                sid,
                TraceId(new_id()),
            )
        runtime.store.close(sid)
    from datetime import timedelta

    from adam.intelligence.service import Goal, Intelligence, Link
    from adam.memory.service import Evidence

    with runtime.store.connect() as db:
        if db.execute("SELECT 1 FROM runtime_metadata WHERE key='portfolio_demo_v1'").fetchone():
            return
        sid = SessionId(new_id())
        runtime.store.create(sid)
        from adam.core.contracts import utc_now

        source = runtime.memories.remember(
            db,
            key="Fictional Cedar project",
            content="Fictional Cedar uses Example Studio.",
            kind="project",
            evidence=Evidence(
                source="synthetic_fixture",
                source_actor="synthetic_fixture",
                session_id=sid,
                trace_id=TraceId(new_id()),
                timestamp=utc_now(),
            ),
        )
        for days in [1, 2, 3]:
            runtime.memories.remember(
                db,
                key=f"Fictional review {days}",
                content="Fictional Cedar project review.",
                kind="episodic",
                evidence=Evidence(
                    source="synthetic_fixture",
                    source_actor="synthetic_fixture",
                    session_id=sid,
                    trace_id=TraceId(new_id()),
                    timestamp=utc_now() - timedelta(days=days),
                ),
            )
    personal = Intelligence(runtime.memories)
    personal.link(
        Link(memory_id=source.memory_id, subject="Cedar", relation="uses", object="Example Studio")
    )
    personal.save_goal(Goal(title="Prepare the fictional Cedar demonstration", project="Cedar"))
    with runtime.store.connect() as db:
        db.execute("INSERT OR IGNORE INTO runtime_metadata VALUES ('portfolio_demo_v1','seeded')")
    runtime.store.close(sid)


class AuthBoundary:
    def __init__(self, app: ASGIApp, auth: AuthManager, pool: RuntimePool) -> None:
        self.app, self.auth, self.pool = app, auth, pool

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        path = scope.get("path", "")
        origin = connection.headers.get("origin")
        allowed_origins = {"http://localhost:8765", "http://127.0.0.1:8765"}
        if origin and origin not in allowed_origins:
            await self.deny(scope, receive, send, "AUTH.ORIGIN_DENIED", 403)
            return
        public = path in {
            "/console",
            "/console.js",
            "/console.css",
            "/health",
            "/docs",
            "/openapi.json",
            "/docs/oauth2-redirect",
            "/auth/login",
            "/auth/session",
        }
        if public:
            await self.app(scope, receive, send)
            return
        try:
            if connection.query_params.get("access_token") is not None:
                raise AuthError("AUTH.URL_TOKEN_DENIED")
            token = request_token(connection)
            principal = await asyncio.to_thread(self.auth.resolve, token)
            if path.startswith("/developer/") and not (
                principal.mode == "owner" and principal.elevated
            ):
                raise AuthError("AUTH.ELEVATION_REQUIRED")
            if path.startswith(("/vault/", "/maintenance/")) and not (
                principal.mode == "owner" and principal.elevated
            ):
                raise AuthError("AUTH.ELEVATION_REQUIRED")
            if principal.mode != "owner" and (
                path.startswith(
                    ("/operations", "/internet", "/vision", "/computer", "/distribution")
                )
                or (path == "/knowledge/sources" and scope.get("method") == "POST")
                or path.startswith("/auth/elevate")
                or (path.startswith("/memory") and scope.get("method") == "DELETE")
            ):
                raise AuthError("POLICY.OWNER_REQUIRED")
            runtime = await self.pool.get(principal)
        except AuthError as exc:
            await self.deny(
                scope, receive, send, exc.code, 401 if exc.code == "AUTH.REQUIRED" else 403
            )
            return
        if (
            path.startswith(
                ("/vision", "/computer", "/distribution", "/personal", "/training", "/portfolio")
            )
            and scope.get("method") == "POST"
        ):
            limit = 4_210_000 if path == "/vision/analyze" else 65536
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                try:
                    self.auth.resolve(token)
                except AuthError:
                    await self.deny(scope, receive, send, "AUTH.REQUIRED", 401)
                    return
                body.extend(message.get("body", b""))
                if len(body) > limit:
                    await self.deny(scope, receive, send, "VISION.INPUT_LIMIT", 413)
                    return
                if not message.get("more_body", False):
                    break
            original_receive = receive
            consumed = False

            async def vision_receive() -> Any:
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await original_receive()

            receive = vision_receive
        marker = CURRENT.set(runtime)

        def verify_authority() -> None:
            current = self.auth.resolve(token)
            if path.startswith(("/developer/", "/maintenance/", "/vault/")) and not (
                current.mode == "owner" and current.elevated
            ):
                raise AuthError("AUTH.ELEVATION_REQUIRED")
            if path.startswith("/training") and not (current.mode == "owner" and current.elevated):
                raise AuthError("AUTH.ELEVATION_REQUIRED")
            if (
                path.startswith("/distribution/")
                and path
                not in {"/distribution/setup", "/distribution/cancel", "/distribution/model"}
                and not (current.mode == "owner" and current.elevated)
            ):
                raise AuthError("AUTH.ELEVATION_REQUIRED")
            if path in {
                "/internet/connect",
                "/internet/approve",
                "/internet/execute",
                "/vision/capture",
                "/vision/windows",
                "/computer/windows",
                "/computer/observe",
                "/computer/plan",
                "/computer/approve",
                "/computer/execute",
            } and not (current.mode == "owner" and current.elevated):
                raise AuthError("AUTH.ELEVATION_REQUIRED")

        authority_marker = AUTHORITY.set(verify_authority)
        response_started = False

        async def guarded_send(message: Any) -> None:
            nonlocal response_started
            if path not in {"/auth/logout", "/auth/switch"} and message["type"] in {
                "http.response.start",
                "http.response.body",
                "websocket.send",
                "websocket.accept",
            }:
                try:
                    self.auth.resolve(token)
                except AuthError:
                    if scope["type"] == "websocket":
                        await send({"type": "websocket.close", "code": 1008})
                    else:
                        if response_started:
                            await send(
                                {"type": "http.response.body", "body": b"", "more_body": False}
                            )
                        else:
                            await self.deny(scope, receive, send, "AUTH.REQUIRED", 401)
                    raise AuthError("AUTH.REQUIRED") from None
            await send(message)
            if message["type"] == "http.response.start":
                response_started = True

        try:

            async def guarded_receive() -> Any:
                message = await receive()
                if message["type"] == "websocket.receive":
                    try:
                        self.auth.resolve(token)
                    except AuthError:
                        await send({"type": "websocket.close", "code": 1008})
                        raise WebSocketDisconnect(1008) from None
                return message

            await self.app(scope, guarded_receive, guarded_send)
        except AuthError:
            pass
        finally:
            CURRENT.reset(marker)
            AUTHORITY.reset(authority_marker)

    @staticmethod
    async def deny(scope: Scope, receive: Receive, send: Send, code: str, status: int) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await JSONResponse(status_code=status, content={"error": code})(scope, receive, send)
