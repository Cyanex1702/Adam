import argparse
import asyncio
import hmac
import json
import os
import secrets
import socket
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any

import portalocker
import uvicorn
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from adam import APP_VERSION
from adam.api.app import create_app
from adam.compute.catalog import Catalog, ModelProfile, publish
from adam.compute.hardware import assets_root
from adam.core.config import Settings, load_settings, resolve_catalog_settings
from adam.core.runtime import ChatRequest
from adam.evals.suite import ProbeProvider
from adam.resilience.archive import scoped
from adam.resilience.recovery import inspect
from adam.security.auth import AuthError
from adam.security.gateway import CURRENT


def adopt_initial_runtime(settings: Settings) -> None:
    """Manage the already selected installed weights; never select a new model."""
    root = assets_root()
    identifier = settings.model.model_id
    if identifier not in {"qwen3-4b-instruct", "qwen3-4b-abliterated"}:
        return
    if (
        not (root / "models" / (identifier + ".gguf")).is_file()
        or not (root / "runtime/llama/llama-server.exe").is_file()
    ):
        return
    catalog = scoped(settings.data_dir, "config/model-catalog.json")
    lock_path = scoped(settings.data_dir, "compute/control.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(str(lock_path), mode="a+b", timeout=0):
        if not catalog.exists():
            publish(
                settings.data_dir,
                "config/model-catalog.json",
                Catalog(
                    profiles={
                        "current": ModelProfile(
                            profile_id="current",
                            model=settings.model,
                            managed=True,
                            model_file=identifier + ".gguf",
                            device="cpu",
                        )
                    }
                ),
            )


class DesktopBoundary:
    """Private pipe-issued capability, in addition to ordinary ADAM authentication.

    This wrapper is installed only by the owned desktop sidecar. The ordinary API
    has no first-launch setup route. No browser origin gains desktop authority.
    """

    def __init__(self, app: ASGIApp, nonce: str, ready: Any) -> None:
        self.app, self.nonce, self.ready = app, nonce, ready

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        supplied = request.headers.get("x-adam-desktop", "")
        if not hmac.compare_digest(
            supplied.encode("utf-8"), self.nonce.encode("utf-8")
        ) or request.headers.get("origin"):
            await JSONResponse({"error": "DESKTOP.ACCESS_DENIED"}, status_code=403)(
                scope, receive, send
            )
            return
        if request.url.path == "/desktop/status" and request.method == "GET":
            app = self.ready
            recovery = not hasattr(app.state, "auth")
            manager = app.state.models.manager if not recovery else None
            # Connection polling must never wait on inference-server networking.
            healthy = (
                manager is not None
                and not manager.error
                and not manager.detached
                and manager.state in {"LOADED", "IDLE", "ACTIVE"}
                and (manager.last_health is None or manager.last_health.status == "HEALTHY")
            )
            await JSONResponse(
                {
                    "release": APP_VERSION,
                    "configured": app.state.auth.configured() if not recovery else False,
                    "recovery": recovery,
                    "model_status": "HEALTHY" if healthy else "UNAVAILABLE",
                    "model_error": (
                        manager.error
                        or (manager.last_health.reason if manager.last_health else None)
                    )
                    if manager
                    else "RECOVERY.READ_ONLY",
                    "model_status_source": "lifecycle",
                    "issues": getattr(app.state, "recovery_issues", []),
                }
            )(scope, receive, send)
            return
        if request.url.path == "/desktop/diagnostics" and request.method == "GET":
            from adam.compute.diagnostics import report

            app = self.ready
            value = await asyncio.to_thread(
                report,
                app.state.desktop_settings,
                app.state.models.manager if hasattr(app.state, "models") else None,
                getattr(app.state, "recovery_issues", []),
            )
            await JSONResponse(value)(scope, receive, send)
            return
        if request.url.path == "/desktop/setup":
            if request.method != "POST" or not hasattr(self.ready.state, "auth"):
                response = JSONResponse({"error": "DESKTOP.SETUP_UNAVAILABLE"}, status_code=409)
            else:
                try:
                    body = bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body) > 8192:
                            raise ValueError
                    value = json.loads(body)
                    if set(value) != {"password"} or not isinstance(value["password"], str):
                        raise ValueError
                    await asyncio.to_thread(self.ready.state.auth.initialize, value["password"])
                    response = JSONResponse({"configured": True})
                except AuthError as error:
                    response = JSONResponse({"error": error.code}, status_code=409)
                except (ValueError, TypeError):
                    response = JSONResponse({"error": "INPUT.INVALID"}, status_code=422)
            await response(scope, receive, send)
            return
        if (
            request.url.path.startswith(("/voice/", "/developer/voice/"))
            and request.method == "POST"
        ):
            limit = (
                2_570_000
                if request.url.path in {"/voice/transcribe", "/developer/voice/enroll"}
                else 16384
            )
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > limit:
                    await JSONResponse({"error": "VOICE.INPUT_LIMIT"}, status_code=413)(
                        scope, receive, send
                    )
                    return
            consumed = False

            async def bounded_receive() -> Any:
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, bounded_receive, send)
            return
        await self.app(scope, receive, send)


def desktop_app(settings: Settings, nonce: str, *, probe: bool = False) -> DesktopBoundary:
    settings = resolve_catalog_settings(settings)
    if not probe and inspect(settings)["mode"] == "HEALTHY":
        adopt_initial_runtime(settings)
    app = create_app(settings, ProbeProvider() if probe else None)
    app.state.desktop_settings = settings
    if hasattr(app.state, "auth"):
        from adam.voice.api import install_voice

        install_voice(app, settings, app.state.models.manager)
        from adam.mesh.service import install_mesh

        install_mesh(app)

        @app.post("/desktop/chat")
        async def stream_chat(body: ChatRequest) -> StreamingResponse:
            runtime = CURRENT.get()

            from adam.security.request import AUTHORITY, check_authority

            original = AUTHORITY.get()

            def authority() -> None:
                if original:
                    original()
                if (
                    body.session_id
                    and runtime.principal.mode == "owner"
                    and hasattr(app.state, "mesh")
                ):
                    if app.state.mesh.store.primary(str(body.session_id))["primary"] != "desktop":
                        from adam.mesh.contracts import MeshError

                        raise MeshError("MESH.NOT_PRIMARY")

            authority()

            async def events() -> Any:
                marker = AUTHORITY.set(authority)
                try:
                    async for event in runtime.stream(body):
                        check_authority()
                        yield event.model_dump_json() + "\n"
                finally:
                    AUTHORITY.reset(marker)

            return StreamingResponse(
                events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"}
            )

    return DesktopBoundary(app, nonce, app)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Owned local ADAM desktop service")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--probe", action="store_true", help="Explicit synthetic QA transport")
    args = parser.parse_args()
    configuration_error = False
    try:
        settings = load_settings(None if os.environ.get("ADAM_CONFIG") else args.config)
    except (ValueError, OSError):
        from adam.core.config import resolve_data_dir

        settings = Settings(data_dir=args.data_dir or resolve_data_dir())
        configuration_error = True
    if args.data_dir and not configuration_error:
        # Explicit local OS-trusted testing option; normal desktop IPC has no path input.
        settings = load_settings(args.config, env={"ADAM_DATA_DIR": str(args.data_dir)})
    restored = os.environ.get("ADAM_RESTORED_CONFIG")
    if restored:
        selected = Settings.model_validate_json(Path(restored).read_bytes())
        if selected.data_dir.resolve() != settings.data_dir.resolve():
            raise RuntimeError("RESTORE.CONFIG_PATH_MISMATCH")
        settings = selected
    lease = portalocker.Lock(str(settings.data_dir / "desktop.lease"), mode="a+b", timeout=0)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    lease.acquire()
    nonce = secrets.token_urlsafe(48)
    if configuration_error:
        from adam.resilience.recovery import recovery_app

        ready = recovery_app(settings, ["CONFIG.INVALID"])
        ready.state.desktop_settings = settings
        app = DesktopBoundary(ready, nonce, ready)
    else:
        app = desktop_app(settings, nonce, probe=args.probe)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, access_log=False, log_level="error", timeout_graceful_shutdown=10)
    )

    def control() -> None:
        # EOF includes a crashed native parent; no credentials or arbitrary commands.
        for line in sys.stdin:
            if line.strip() == "stop":
                break
        server.should_exit = True

    threading.Thread(target=control, daemon=True).start()
    worker = threading.Thread(target=lambda: server.run(sockets=[listener]))
    worker.start()
    try:
        for _ in range(240):
            if server.started:
                print(json.dumps({"event": "ready", "port": port, "nonce": nonce}), flush=True)
                break
            if not worker.is_alive():
                raise RuntimeError("DESKTOP.START_FAILED")
            time.sleep(0.5)
        else:
            raise RuntimeError("DESKTOP.START_TIMEOUT")
        worker.join()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
        lease.release()


def main() -> None:
    try:
        _main()
    except portalocker.exceptions.LockException:
        print(json.dumps({"event": "failed", "error": "DESKTOP.PROFILE_IN_USE"}), flush=True)
        raise SystemExit(1) from None
    except (ValueError, OSError, sqlite3.Error) as error:
        code = getattr(error, "code", "DESKTOP.START_FAILED")
        if (
            not isinstance(code, str)
            or len(code) > 100
            or not all(c.isupper() or c.isdigit() or c in "._" for c in code)
        ):
            code = "DESKTOP.START_FAILED"
        print(json.dumps({"event": "failed", "error": code}), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
