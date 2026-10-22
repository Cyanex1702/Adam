import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import Field, SecretStr

from adam.core.config import Settings
from adam.core.contracts import Contract, new_id
from adam.distribution.portable import DistributionError, Portable
from adam.distribution.releases import Releases
from adam.distribution.setup import Setup
from adam.resilience.archive import scoped
from adam.resilience.restore import rebuild_indexes
from adam.security.auth import AuthError
from adam.security.gateway import request_token
from adam.security.request import REMOTE_DEVICE, check_authority


class Package(Contract):
    path: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    channel: Literal["stable", "beta", "dev"] = "stable"


class Authorization(Contract):
    id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    mode: Literal["update", "rollback", "restore"] = "update"


class Handoff(Contract):
    ticket: str = Field(pattern=r"^[a-f0-9-]{36}$")
    token: str = Field(min_length=30, max_length=100)


class Backup(Contract):
    password: SecretStr = Field(min_length=12, max_length=1024)


class Restore(Backup):
    path: str = Field(min_length=1, max_length=1024)


class Model(Contract):
    model_id: Literal["qwen3-4b-instruct", "qwen3-4b-abliterated"]


def install_distribution(app: FastAPI, settings: Settings) -> None:
    releases, setup = Releases(settings), Setup(settings)
    app.state.distribution = releases
    app.state.setup = setup
    model_task: asyncio.Task[None] | None = None

    def owner(request: Request, elevated: bool = True) -> str:
        token = request_token(request)
        principal = app.state.auth.resolve(token)
        if principal.mode != "owner" or REMOTE_DEVICE.get():
            raise AuthError("POLICY.OWNER_REQUIRED")
        if elevated and not principal.elevated:
            raise AuthError("AUTH.ELEVATION_REQUIRED")
        check_authority()
        return str(app.state.auth._hash(token))

    @app.exception_handler(DistributionError)
    async def error(request: Request, exc: DistributionError) -> JSONResponse:
        return JSONResponse({"error": exc.code}, status_code=409)

    @app.get("/distribution")
    async def status(request: Request) -> dict[str, Any]:
        owner(request, False)
        return {
            **releases.status(),
            "last_result": json.loads((releases.root / "last-result.json").read_bytes())
            if (releases.root / "last-result.json").exists()
            else None,
        }

    @app.get("/distribution/setup")
    async def checks(request: Request) -> dict[str, Any]:
        owner(request, False)
        return await asyncio.to_thread(setup.report)

    @app.post("/distribution/model")
    async def model(request: Request, value: Model) -> dict[str, Any]:
        nonlocal model_task
        owner(request)
        if model_task is not None and not model_task.done():
            raise DistributionError("SETUP.BUSY_OR_UNKNOWN")
        setup.cancel.clear()
        setup.progress = {"status": "QUEUED", "bytes": 0}

        async def download() -> None:
            try:
                await asyncio.to_thread(setup.install, value.model_id)
            except Exception as exc:
                setup.progress.update(
                    status="FAILED_OR_CANCELLED",
                    error=getattr(exc, "code", "SETUP.DOWNLOAD_OR_IO_FAILED"),
                )

        # The copied authority context checks the owner session throughout the bounded
        # pinned download. Revocation and explicit cancellation remain effective.
        model_task = asyncio.create_task(download())
        return {"status": "QUEUED", "note": "Refresh setup progress; ADAM must stay open."}

    @app.post("/distribution/cancel")
    async def cancel(request: Request) -> dict[str, Any]:
        owner(request, False)
        setup.cancel.set()
        return {"status": "CANCELLATION_REQUESTED"}

    @app.post("/distribution/stage")
    async def stage(request: Request, value: Package) -> dict[str, Any]:
        owner(request)
        return await asyncio.to_thread(
            releases.stage, Path(value.path), value.sha256, value.channel
        )

    @app.post("/distribution/authorize")
    async def authorize(request: Request, value: Authorization) -> dict[str, Any]:
        return releases.authorize(value.id, owner(request), value.mode)

    @app.post("/distribution/handoff")
    async def handoff(request: Request, value: Handoff) -> dict[str, Any]:
        key = owner(request)
        record = json.loads(scoped(releases.root, "tickets/" + value.ticket + ".json").read_bytes())
        import hmac

        if (
            record["owner"] != key
            or record["expires"] < time.time()
            or not hmac.compare_digest(
                record["token_hash"], hashlib.sha256(value.token.encode()).hexdigest()
            )
        ):
            raise DistributionError("UPDATE.APPROVAL_REQUIRED")
        return {"home": str(releases.home), "data": str(settings.data_dir)}

    @app.post("/distribution/backup")
    async def backup(request: Request, value: Backup) -> dict[str, Any]:
        owner(request)
        target = releases.root / "exports" / (new_id() + ".adamportable")
        result = await asyncio.to_thread(
            Portable().create, settings, value.password.get_secret_value(), target
        )
        return {**result, "path": str(target)}

    @app.post("/distribution/restore")
    async def restore(request: Request, value: Restore) -> dict[str, Any]:
        owner(request)
        identifier = new_id()
        target = releases.path(identifier) / "data"
        result = await asyncio.to_thread(
            Portable().restore, Path(value.path), value.password.get_secret_value(), target
        )
        return {**result, "id": identifier, "status": "STAGED_RESTORE"}

    @app.post("/distribution/reindex")
    async def reindex(request: Request) -> dict[str, Any]:
        owner(request)
        return await asyncio.to_thread(rebuild_indexes, settings)
