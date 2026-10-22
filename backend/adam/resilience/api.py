import asyncio
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field, SecretStr

from adam.core.config import Settings
from adam.core.contracts import Contract
from adam.resilience.archive import BackupService, scoped
from adam.resilience.contracts import BackupError, Generation, Receipt
from adam.resilience.export import ExportFilter, ExportService
from adam.resilience.restore import RestoreService


class BackupRequest(Contract):
    password: SecretStr
    generation: Generation = "daily"
    include_vault: bool = False


class UnlockRequest(Contract):
    password: SecretStr


class RestoreRequest(UnlockRequest):
    restore_vault: bool = False


class ExportIdentifier(Contract):
    identifier: str = Field(pattern=r"^[a-f0-9-]{36}$")


def install_maintenance(app: FastAPI, settings: Settings) -> None:
    service = BackupService(settings)

    @app.exception_handler(BackupError)
    async def backup_error(request: Request, error: BackupError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": error.code})

    @app.post("/maintenance/backups")
    async def backup(body: BackupRequest) -> Receipt:
        return await asyncio.to_thread(
            service.create,
            body.password.get_secret_value(),
            generation=body.generation,
            include_vault=body.include_vault,
        )

    @app.get("/maintenance/backups")
    async def backups() -> list[dict[str, object]]:
        return await asyncio.to_thread(service.list)

    @app.post("/maintenance/backups/{identifier}/verify")
    async def verify(identifier: str, body: UnlockRequest) -> dict[str, Any]:
        manifest, _ = await asyncio.to_thread(
            service.read, service.path(identifier), body.password.get_secret_value()
        )
        return {
            "status": "VERIFIED",
            "files": len(manifest.files),
            "schemas": manifest.schemas,
            "identity_digest": manifest.identity_digest,
            "vault_included": manifest.vault_included,
        }

    @app.get("/maintenance/backups/{identifier}/download")
    async def download(identifier: str) -> FileResponse:
        path = service.path(identifier)
        if not path.is_file():
            raise BackupError("BACKUP.NOT_FOUND")
        return FileResponse(path, media_type="application/octet-stream", filename=identifier)

    @app.post("/maintenance/backups/{identifier}/restore")
    async def restore(identifier: str, body: RestoreRequest) -> dict[str, object]:
        from adam.core.contracts import new_id

        target = service.root / "restores" / new_id()
        return await asyncio.to_thread(
            RestoreService().restore,
            service.path(identifier),
            body.password.get_secret_value(),
            target,
            restore_vault=body.restore_vault,
        )

    @app.get("/maintenance/integrity")
    async def integrity() -> dict[str, object]:
        from adam.resilience.recovery import inspect

        return await asyncio.to_thread(inspect, settings)

    @app.post("/maintenance/exports")
    async def export(body: ExportFilter) -> dict[str, Any]:
        from adam.core.contracts import new_id

        identifier = new_id()
        receipt = await asyncio.to_thread(
            ExportService(settings).export, scoped(service.root, "exports/" + identifier), body
        )
        return {**receipt, "export_id": identifier}

    @app.get("/maintenance/exports/{identifier}/{filename}")
    async def exported_file(identifier: str, filename: str) -> FileResponse:
        if filename not in {
            "data.json",
            "data.jsonl",
            "summary.md",
            "records.csv",
            "export-manifest.json",
        }:
            raise BackupError("EXPORT.FILE_NOT_FOUND")
        try:
            ExportIdentifier(identifier=identifier)
        except ValueError:
            raise BackupError("EXPORT.ID_INVALID") from None
        path = scoped(service.root, "exports/" + identifier + "/" + filename)
        if not path.is_file():
            raise BackupError("EXPORT.FILE_NOT_FOUND")
        return FileResponse(path, filename=filename, media_type="application/octet-stream")
