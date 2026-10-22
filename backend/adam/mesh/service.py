import asyncio
import hashlib
import ipaddress
import json
import socket
import sqlite3
import ssl
import time
from contextlib import asynccontextmanager, suppress
from importlib.resources import files
from typing import Any
from uuid import UUID

import uvicorn
from fastapi import FastAPI
from fastapi import Request as HTTPRequest
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.types import ASGIApp, Receive, Scope, Send

from adam.core.contracts import SessionId, TraceId, new_id
from adam.core.privacy import contains_secret, safe_transcript
from adam.core.runtime import ChatRequest, Runtime
from adam.memory.service import parse_command
from adam.mesh.contracts import Approval, Claim, Device, Handoff, MeshError, Packet, Request, Share
from adam.mesh.crypto import decode, packet, verify
from adam.mesh.store import MeshStore
from adam.resilience.archive import scoped
from adam.security.gateway import CURRENT
from adam.security.request import AUTHORITY, REMOTE_DEVICE, check_authority
from adam.security.vault import DPAPI
from adam.voice.contracts import AudioInput, SpeechInput
from adam.voice.providers import decode_audio, noise_process


class NetworkBoundary:
    def __init__(self, app: ASGIApp, manager: "MeshManager") -> None:
        self.app, self.manager = app, manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await self.app(scope, receive, send)
            return
        request = HTTPRequest(scope, receive)
        expected = self.manager.origin
        if (
            request.headers.get("host") != expected.removeprefix("https://")
            or (request.headers.get("origin") not in {None, expected})
            or scope.get("scheme") != "https"
        ):
            await JSONResponse({"error": "MESH.ORIGIN_DENIED"}, status_code=403)(
                scope, receive, send
            )
            return
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 3_600_000:
                await JSONResponse({"error": "MESH.INPUT_LIMIT"}, status_code=413)(
                    scope, receive, send
                )
                return
        consumed = False

        async def bounded() -> Any:
            nonlocal consumed
            if consumed:
                return await receive()
            consumed = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        denied = False
        started = False

        async def guarded(message: Any) -> None:
            nonlocal denied, started
            if denied:
                return
            if message["type"] == "http.response.start":
                message["headers"].extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; style-src 'self'; "
                            b"connect-src 'self'; img-src 'self' data:; object-src 'none'; "
                            b"frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                        ),
                    ]
                )
            guard = scope.get("state", {}).get("mesh_guard")
            if guard and message["type"] in {"http.response.start", "http.response.body"}:
                try:
                    guard()
                except (MeshError, ValueError):
                    denied = True
                    if not started:
                        await JSONResponse({"error": "MESH.DEVICE_DENIED"}, status_code=403)(
                            scope, bounded, send
                        )
                    else:
                        await send({"type": "http.response.body", "body": b"", "more_body": False})
                    return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, bounded, guarded)


class MeshManager:
    def __init__(self, app: FastAPI, *, store: MeshStore | None = None) -> None:
        self.app = app
        self.runtime: Runtime = app.state.runtime
        self.store = store or MeshStore(self.runtime.settings.data_dir)
        self.server: uvicorn.Server | None = None
        self.task: asyncio.Task[None] | None = None
        self.listener: socket.socket | None = None
        self.origin = "https://127.0.0.1:9443"
        self.lock = asyncio.Lock()
        self.pending = 0
        self.attempts: dict[str, tuple[int, float]] = {}
        mobile = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        self.public = NetworkBoundary(mobile, self)

        @mobile.exception_handler(MeshError)
        async def error(request: HTTPRequest, exc: MeshError) -> JSONResponse:
            return JSONResponse({"error": exc.code}, status_code=403)

        @mobile.exception_handler(ValidationError)
        @mobile.exception_handler(RequestValidationError)
        async def invalid(request: HTTPRequest, exc: ValidationError) -> JSONResponse:
            return JSONResponse({"error": "MESH.INVALID_PACKET"}, status_code=422)

        @mobile.get("/")
        async def index() -> Response:
            return Response(
                files("adam.mesh").joinpath("web/index.html").read_bytes(), media_type="text/html"
            )

        @mobile.get("/client.js")
        async def javascript() -> Response:
            return Response(
                files("adam.mesh").joinpath("web/client.js").read_bytes(),
                media_type="text/javascript",
            )

        @mobile.get("/style.css")
        async def css() -> Response:
            return Response(
                files("adam.mesh").joinpath("web/style.css").read_bytes(), media_type="text/css"
            )

        @mobile.post("/pair")
        async def pair(body: Claim, request: HTTPRequest) -> dict[str, str]:
            address = request.client.host if request.client else "unknown"
            count, start = self.attempts.get(address, (0, time.monotonic()))
            if time.monotonic() - start > 60:
                count, start = 0, time.monotonic()
            if count >= 5:
                raise MeshError("MESH.PAIR_RATE_LIMIT")
            if len(self.attempts) >= 128 and address not in self.attempts:
                raise MeshError("MESH.PAIR_RATE_LIMIT")
            self.attempts[address] = (count + 1, start)
            return await asyncio.to_thread(self.store.claim, body)

        @mobile.post("/rpc")
        async def rpc(body: Packet, request: HTTPRequest) -> dict[str, str]:
            raw = decode(body.message)
            value = Request.model_validate_json(raw)
            if abs(time.time() - value.issued_at) > 60:
                raise MeshError("MESH.REQUEST_EXPIRED")
            device = str(value.device_id)
            record = self.store.device(device, pending=value.operation == "status")
            verify(record["pub"], raw, body.signature)
            if record["status"] == "PENDING":
                return packet(
                    self.store.key,
                    {
                        "protocol": 1,
                        "request_id": str(value.request_id),
                        "node_id": self.store.node_id,
                        "status": "PENDING",
                        "payload": {},
                    },
                )
            if value.operation == "status":
                # Revocation/health polls must not queue behind a long model turn.
                # This read-only path cannot access memory, history or tools.
                def status_authority() -> None:
                    self.authorize(value)

                status_authority()
                request.state.mesh_guard = status_authority
                payload = await self.execute(value)
                status_authority()
                return packet(
                    self.store.key,
                    {
                        "protocol": 1,
                        "request_id": str(value.request_id),
                        "node_id": self.store.node_id,
                        "status": "VERIFIED",
                        "operation": "status",
                        "payload": payload,
                    },
                )
            if self.pending >= 4:
                raise MeshError("MESH.BUSY")
            self.pending += 1
            try:
                async with self.lock:

                    def authority() -> None:
                        self.authorize(value)

                    authority()
                    request.state.mesh_guard = authority
                    marker = AUTHORITY.set(authority)
                    remote = REMOTE_DEVICE.set(device)
                    try:
                        digest = hashlib.sha256(
                            json.dumps(
                                {"operation": value.operation, "payload": value.payload},
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest()
                        readonly = value.operation in {"status", "session"}
                        previous = (
                            None
                            if readonly
                            else self.store.reserve(device, str(value.request_id), digest)
                        )
                        if previous is not None:
                            authority()
                            return packet(self.store.key, previous)
                        try:
                            payload = await self.execute(value)
                            result = {
                                "protocol": 1,
                                "request_id": str(value.request_id),
                                "node_id": self.store.node_id,
                                "status": "VERIFIED",
                                "operation": value.operation,
                                "payload": payload,
                            }
                        except (MeshError, ValueError) as exc:
                            code = exc.code if isinstance(exc, MeshError) else "MESH.INPUT_INVALID"
                            result = {
                                "protocol": 1,
                                "request_id": str(value.request_id),
                                "node_id": self.store.node_id,
                                "status": "ERROR",
                                "error": code,
                                "payload": {},
                            }
                        except Exception:
                            result = {
                                "protocol": 1,
                                "request_id": str(value.request_id),
                                "node_id": self.store.node_id,
                                "status": "ERROR",
                                "error": "MESH.OPERATION_FAILED",
                                "payload": {},
                            }
                        authority()
                        retained = (
                            result
                            if value.operation not in {"transcribe", "speak"}
                            else {
                                **result,
                                "status": "ERROR",
                                "error": "MESH.VOLATILE_RESULT_EXPIRED",
                                "payload": {},
                            }
                        )
                        if not readonly:
                            self.store.complete(device, str(value.request_id), retained)
                        return packet(self.store.key, result)
                    finally:
                        AUTHORITY.reset(marker)
                        REMOTE_DEVICE.reset(remote)
            finally:
                self.pending -= 1

    def authorize(self, value: Request) -> None:
        device = str(value.device_id)
        record = self.store.device(device)
        if value.operation == "search" and not record["search"]:
            raise MeshError("MESH.CAPABILITY_DENIED")
        if value.operation in {"transcribe", "speak"} and not record["voice"]:
            raise MeshError("MESH.CAPABILITY_DENIED")
        if value.operation in {"session", "chat", "handoff", "speak"}:
            try:
                session = str(UUID(str(value.payload.get("session_id", ""))))
            except ValueError:
                raise MeshError("MESH.INPUT_INVALID") from None
            self.store.allowed_session(device, session)
            if (
                value.operation in {"chat", "speak"}
                and self.store.primary(session)["primary"] != device
            ):
                raise MeshError("MESH.NOT_PRIMARY")

    def session(self, identifier: str) -> dict[str, Any]:
        sid = SessionId(identifier)
        row = self.runtime.store.get(sid)
        if not row or row["closed"]:
            raise MeshError("MESH.SESSION_UNAVAILABLE")
        return {
            "session_id": identifier,
            "history": self.runtime.store.history(sid, limit=50),
            "working": self.runtime.store.working(sid).model_dump(),
            **self.store.primary(identifier),
            "pending_approvals": "CORE_ONLY; approve on desktop",
        }

    async def execute(self, value: Request) -> dict[str, Any]:
        body, device = value.payload, str(value.device_id)
        if "session_id" in body:
            body = {**body, "session_id": str(UUID(str(body["session_id"])))}
        allowed = {
            "status": set(),
            "new_session": set(),
            "session": {"session_id"},
            "handoff": {"session_id", "primary"},
            "chat": {"session_id", "text"},
            "search": {"query"},
            "speak": {"session_id", "text", "engine", "language"},
            "transcribe": {"pcm16", "sample_rate", "language", "mode", "partial", "silence_ms"},
        }
        if set(body) - allowed[value.operation]:
            raise MeshError("MESH.INPUT_INVALID")
        if value.operation == "status":
            health = await self.runtime.provider.health_check()
            operations = getattr(self.app.state, "operations", None)
            updates = []
            if operations:
                try:
                    for sid in self.store.sessions(device):
                        if self.store.primary(sid)["primary"] == device:
                            operations.seen(sid, device)
                    updates = await asyncio.to_thread(
                        operations.inbox, device, lambda sid: self.store.primary(sid)["primary"]
                    )
                except (sqlite3.Error, OSError, ValueError):
                    operations.error = "OPERATIONS.STORE_UNAVAILABLE"
            return {
                "notifications": updates,
                "identity": "ADAM",
                "node_id": self.store.node_id,
                "health": "ONLINE",
                "model_status": health.status,
                "protocol": 1,
                "trust": "OWNER_DEVICE",
                "sessions": self.store.sessions(device),
                "capabilities": {
                    "chat": health.status == "HEALTHY",
                    "filesystem.search": bool(self.store.device(device)["search"]),
                    "voice": bool(self.store.device(device)["voice"])
                    and self.runtime.settings.features.voice,
                },
                "replication": "EXPLICIT_SHARED_SESSIONS_ONLY; no transcript cache",
                "remote_internet": "UNAVAILABLE",
            }
        if value.operation == "new_session":
            sid = self.runtime.sessions.resolve(None, TraceId(new_id())).session_id
            self.store.share(device, str(sid))
            self.store.handoff(str(sid), device)
            return self.session(str(sid))
        if value.operation == "session":
            return self.session(str(body["session_id"]))
        if value.operation == "handoff":
            self.idle(str(body["session_id"]))
            primary = body.get("primary")
            if primary not in {"desktop", device}:
                raise MeshError("MESH.HANDOFF_DENIED")
            return self.store.handoff(str(body["session_id"]), str(primary))
        if value.operation == "chat":
            text = body.get("text")
            if (
                not isinstance(text, str)
                or not 1 <= len(text) <= 4000
                or text.lstrip().startswith("/")
                or parse_command(text)
            ):
                raise MeshError("MESH.COMMAND_DENIED")
            check_authority()
            terminal = None
            async for event in self.runtime.stream(
                ChatRequest(text=text, session_id=SessionId(str(body["session_id"])))
            ):
                check_authority()
                if event.event_type in {"agent.completed", "agent.failed"}:
                    terminal = event
            if terminal is None or terminal.event_type != "agent.completed":
                raise MeshError("MESH.CHAT_UNAVAILABLE")
            return {
                "text": safe_transcript(str(terminal.payload["text"])),
                "session_id": str(body["session_id"]),
                "model_answer": "UNVERIFIED",
                "executed_on": self.store.node_id,
            }
        if value.operation == "search":
            query = body.get("query")
            if (
                not isinstance(query, str)
                or not 1 <= len(query) <= 100
                or contains_secret(query)
                or set(body) != {"query"}
            ):
                raise MeshError("MESH.SEARCH_INPUT_INVALID")
            check_authority()
            found = await asyncio.to_thread(self.runtime.actions.scope.search, ".", query, 30)
            check_authority()
            return {
                "files": found,
                "executed_on": self.store.node_id,
                "scope": "PC tool-sandbox",
                "capability": "filesystem.search",
                "read_only": True,
            }
        if value.operation in {"transcribe", "speak"}:
            voice = self.app.state.voice
            if not self.runtime.settings.features.voice:
                raise MeshError("MESH.VOICE_UNAVAILABLE")
            if self.app.state.models.manager.observe()["mode"] == "DEGRADED":
                raise MeshError("RESOURCE.PRESSURE")
            if value.operation == "speak":
                speech = SpeechInput.model_validate(
                    {k: v for k, v in body.items() if k != "session_id"}
                )
                result: dict[str, Any] = await self.app.state.voice_run(
                    lambda: voice.synthesize(speech)
                )
                return result
            audio = AudioInput.model_validate(body)
            samples = noise_process(decode_audio(audio))
            # The shared bounded lane drains workers before cancellation releases it.
            # Mobile uses STT only: speaker identities/enrollment remain core-only.
            result = await self.app.state.voice_run(
                lambda: voice.transcribe(samples, audio), listening=True
            )
            result["requires_review"] = True  # Mobile never automatically sends recognized speech.
            return result
        raise MeshError("MESH.CAPABILITY_DENIED")

    def idle(self, identifier: str) -> None:
        session = self.runtime.sessions.sessions.get(SessionId(identifier))
        if session and session.busy:
            raise MeshError("MESH.SESSION_BUSY")

    def network(self) -> dict[str, Any]:
        path = scoped(self.runtime.settings.data_dir, "mesh/network.json")
        if not path.is_file() or path.stat().st_size > 4096:
            raise MeshError("MESH.TLS_NOT_CONFIGURED")
        config: dict[str, Any] = json.loads(path.read_bytes())
        address = ipaddress.IPv4Address(config["address"])
        if (
            not (
                address.is_loopback
                or address in ipaddress.IPv4Network("10.0.0.0/8")
                or address in ipaddress.IPv4Network("172.16.0.0/12")
                or address in ipaddress.IPv4Network("192.168.0.0/16")
            )
            or not 1024 <= config["port"] <= 65535
        ):
            raise MeshError("MESH.LAN_ADDRESS_REQUIRED")
        return config

    async def start(self) -> dict[str, Any]:
        check_authority()
        if self.task and not self.task.done():
            return self.status()
        try:
            config = self.network()
            root = self.runtime.settings.data_dir
            cert, key = scoped(root, "mesh/tls/server.pem"), scoped(root, "mesh/tls/key.pem")
            password = DPAPI().open(scoped(root, "mesh/tls/password.dpapi").read_bytes()).decode()
            # Fail before Uvicorn's fatal configuration path for malformed TLS material.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key, password)
        except MeshError:
            raise
        except Exception:
            raise MeshError("MESH.TLS_UNAVAILABLE") from None
        self.origin = f"https://{config['address']}:{config['port']}"
        listener = socket.socket()
        try:
            listener.bind((config["address"], config["port"]))
            listener.listen(16)
            self.server = uvicorn.Server(
                uvicorn.Config(
                    self.public,
                    access_log=False,
                    log_level="error",
                    lifespan="off",
                    ssl_certfile=str(cert),
                    ssl_keyfile=str(key),
                    ssl_keyfile_password=password,
                    timeout_graceful_shutdown=5,
                    limit_concurrency=8,
                )
            )
            self.task = asyncio.create_task(self.server.serve(sockets=[listener]))
            self.listener = listener
            for _ in range(50):
                if self.server.started:
                    check_authority()
                    return self.status()
                if self.task.done():
                    break
                await asyncio.sleep(0.1)
            raise MeshError("MESH.START_FAILED")
        except Exception:
            listener.close()
            await self.stop()
            raise MeshError("MESH.START_FAILED") from None

    async def stop(self) -> dict[str, Any]:
        if self.server:
            self.server.should_exit = True
        if self.task:
            with suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self.task, timeout=10)
        if self.listener:
            self.listener.close()
        self.server, self.task, self.listener = None, None, None
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.runtime.settings.features.mobile_mesh,
            "listening": bool(
                self.server and self.server.started and self.task and not self.task.done()
            ),
            "url": self.origin,
            "node_id": self.store.node_id,
            "public_key": self.store.public_key,
            "devices": self.store.devices(),
            "remote_internet": "UNAVAILABLE",
            "tls_setup": "scripts/setup-mesh.ps1",
            "certificate": str(scoped(self.runtime.settings.data_dir, "mesh/tls/ca.crt")),
        }


def install_mesh(app: FastAPI) -> None:
    if not app.state.runtime.settings.features.mobile_mesh:
        return

    @app.exception_handler(MeshError)
    async def error(request: HTTPRequest, exc: MeshError) -> JSONResponse:
        return JSONResponse({"error": exc.code}, status_code=409)

    try:
        manager = MeshManager(app)
    except Exception:
        # Optional network identity failure must close the mesh, not crash local chat.
        # Never regenerate a key or discard a damaged registry automatically.
        @app.get("/developer/mesh")
        async def unavailable_status() -> dict[str, Any]:
            return {
                "enabled": True,
                "listening": False,
                "url": "",
                "node_id": "",
                "public_key": "",
                "devices": [],
                "certificate": "",
                "error": "MESH.IDENTITY_UNAVAILABLE",
                "remote_internet": "UNAVAILABLE",
            }

        async def unavailable() -> JSONResponse:
            return JSONResponse({"error": "MESH.IDENTITY_UNAVAILABLE"}, status_code=409)

        for action in ("start", "stop", "code", "approve", "revoke", "share", "handoff"):
            app.add_api_route(f"/developer/mesh/{action}", unavailable, methods=["POST"])
        app.add_api_route("/mesh/session-state", unavailable, methods=["POST"])
        return
    app.state.mesh = manager
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(active: FastAPI) -> Any:
        async with original_lifespan(active) as state:
            try:
                yield state
            finally:
                await manager.stop()

    app.router.lifespan_context = lifespan

    @app.get("/developer/mesh")
    async def status() -> dict[str, Any]:
        return manager.status()

    @app.post("/developer/mesh/start")
    async def start() -> dict[str, Any]:
        return await manager.start()

    @app.post("/developer/mesh/stop")
    async def stop() -> dict[str, Any]:
        check_authority()
        return await manager.stop()

    @app.post("/developer/mesh/code")
    async def code() -> dict[str, Any]:
        if not manager.status()["listening"]:
            raise MeshError("MESH.OFFLINE")
        return {"code": manager.store.ticket(), "expires_in_seconds": 300, "url": manager.origin}

    @app.post("/developer/mesh/approve")
    async def approve(body: Approval) -> dict[str, bool]:
        manager.store.approve(str(body.device_id), body.search, body.voice)
        return {"approved": True}

    @app.post("/developer/mesh/revoke")
    async def revoke(body: Device) -> dict[str, bool]:
        manager.store.revoke(str(body.device_id))
        return {"revoked": True}

    @app.post("/developer/mesh/share")
    async def share(body: Share) -> dict[str, Any]:
        manager.session(str(body.session_id))
        manager.store.share(str(body.device_id), str(body.session_id))
        return {"shared": True, "policy": "OWNER_DEVICES", "approvals": "CORE_ONLY"}

    @app.post("/developer/mesh/handoff")
    async def handoff(body: Handoff) -> dict[str, Any]:
        manager.session(str(body.session_id))
        manager.idle(str(body.session_id))
        return manager.store.handoff(str(body.session_id), body.primary)

    @app.post("/mesh/session-state")
    async def session_state(body: Handoff) -> dict[str, Any]:
        if CURRENT.get().principal.mode != "owner":
            raise MeshError("MESH.OWNER_REQUIRED")
        return manager.store.primary(str(body.session_id))
