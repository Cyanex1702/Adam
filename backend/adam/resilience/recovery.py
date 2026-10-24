import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from adam import APP_VERSION
from adam.core.config import Settings, resolve_catalog_settings
from adam.identity.service import IdentityService
from adam.resilience.archive import DB_PATHS, check_db, scoped
from adam.resilience.contracts import BackupError


def recovery_readonly(path: Path) -> sqlite3.Connection:
    from adam.resilience.archive import no_link

    wal = path.with_name(path.name + "-wal")
    no_link(wal)
    no_link(path.with_name(path.name + "-shm"))
    if wal.exists() and wal.stat().st_size:
        with wal.open("rb") as stream:
            header = stream.read(32)
        if len(header) != 32 or header[:4] not in {b"\x37\x7f\x06\x82", b"\x37\x7f\x06\x83"}:
            raise BackupError("STORAGE.WAL_INVALID")
        order: Literal["little", "big"] = "little" if header[3] == 0x82 else "big"
        words = [int.from_bytes(header[i : i + 4], order) for i in range(0, 24, 4)]
        first = second = 0
        for index in range(0, len(words), 2):
            first = (first + words[index] + second) & 0xFFFFFFFF
            second = (second + words[index + 1] + first) & 0xFFFFFFFF
        if (first, second) != (
            int.from_bytes(header[24:28], "big"),
            int.from_bytes(header[28:32], "big"),
        ):
            raise BackupError("STORAGE.WAL_INVALID")
    # immutable=1 ignores WAL state. Let SQLite establish a consistent read
    # transaction instead; mode=ro never checkpoints or writes original DB pages.
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    return db


def storage_issue(error: BaseException) -> str:
    if isinstance(error, BackupError):
        return error.code
    primary = getattr(error, "sqlite_errorcode", 0) & 0xFF
    if primary in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return "STORAGE.BUSY"
    if primary in {sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_READONLY, sqlite3.SQLITE_PERM}:
        return "STORAGE.ACCESS_DENIED"
    if primary == sqlite3.SQLITE_IOERR or isinstance(error, OSError):
        return "STORAGE.IO_FAILED"
    if primary in {sqlite3.SQLITE_ERROR, sqlite3.SQLITE_SCHEMA}:
        return "STORAGE.SCHEMA_MISMATCH"
    return "STORAGE.INTEGRITY_FAILED"


def inspect(settings: Settings) -> dict[str, object]:
    """No migrations, database writes or model calls; SQLite coordinates read locks."""
    settings = resolve_catalog_settings(settings)
    issues: list[str] = []
    stores: dict[str, str] = {}
    schemas: dict[str, int] = {}
    names = [*DB_PATHS]
    if settings.vault_enabled:
        names.append("security/vault.sqlite3")
    for name in names:
        try:
            path = scoped(settings.data_dir, name)
            if not path.exists():
                stores[name] = "ABSENT"
                continue
            with closing(recovery_readonly(path)) as db:
                schemas[name] = check_db(db, name)
            stores[name] = "HEALTHY"
        except (BackupError, sqlite3.Error, OSError) as error:
            code = storage_issue(error)
            stores[name] = code
            issues.append(code)
    try:
        directory = settings.identity_dir or (
            settings.data_dir / "identity" if (settings.data_dir / "identity").exists() else None
        )
        IdentityService(directory)
    except (ValueError, OSError, TypeError, yaml.YAMLError):
        issues.append("IDENTITY.INVALID")
    saved = settings.data_dir / "config" / "restored-settings.json"
    try:
        from adam.compute.catalog import config_digest, read_catalog
        from adam.core.config import load_settings

        catalog = scoped(settings.data_dir, "config/model-catalog.json")
        if catalog.exists():
            registry = read_catalog(catalog)
            if not any(
                config_digest(item.model) == config_digest(settings.model)
                for item in registry.profiles.values()
            ):
                raise ValueError("MODEL.CONFIGURATION_CONFLICT")
        if (settings.data_dir / "config/model-selection.json").exists():
            load_settings(env={"ADAM_DATA_DIR": str(settings.data_dir)})
    except (ValueError, OSError):
        issues.append("MODEL.CONFIGURATION_INVALID")
    if saved.exists():
        try:
            scoped(settings.data_dir, "config/restored-settings.json")
            if saved.stat().st_size > 65536:
                raise ValueError
            Settings.model_validate_json(saved.read_bytes())
        except (ValueError, OSError):
            issues.append("CONFIG.INVALID")
    try:
        preference = scoped(settings.data_dir, "config/performance.json")
        if preference.exists():
            if preference.stat().st_size > 1024:
                raise ValueError
            value = json.loads(preference.read_bytes())
            if set(value) != {"mode"} or value["mode"] not in {"eco", "priority"}:
                raise ValueError
    except (ValueError, OSError):
        issues.append("CONFIG.PERFORMANCE_INVALID")
    return {
        "mode": "RECOVERY_READ_ONLY" if issues else "HEALTHY",
        "issues": sorted(set(issues)),
        "stores": stores,
        "schemas": schemas,
        "model_required": False,
        "derived_indexes": "REBUILDABLE_NOT_CRITICAL",
    }


class RecoveryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def status(self) -> dict[str, object]:
        return inspect(self.settings)

    def records(self, table: str, limit: int = 100) -> list[dict[str, object]]:
        if table not in {"memories", "sessions", "knowledge_sources"}:
            raise BackupError("RECOVERY.READ_ONLY")
        path = scoped(self.settings.data_dir, "runtime.sqlite3")
        try:
            with closing(recovery_readonly(path)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                return [
                    dict(row)
                    for row in db.execute(
                        f"SELECT * FROM {table} LIMIT ?", (max(1, min(limit, 1000)),)
                    )
                ]
        except sqlite3.Error:
            raise BackupError("RECOVERY.STORE_UNREADABLE") from None


def recovery_app(settings: Settings, initial_issues: list[str] | None = None) -> FastAPI:
    app = FastAPI(title="ADAM recovery - local CLI required", version=APP_VERSION)
    app.state.recovery_issues = initial_issues or inspect(settings)["issues"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])

    @app.middleware("http")
    async def read_only(request: Request, call_next: object) -> JSONResponse:
        # No authentication store is initialized, and no private records are served.
        # Use the local OS-trusted recovery CLI for inspection/export/isolated restore.
        return JSONResponse(
            status_code=200 if request.url.path == "/health" and request.method == "GET" else 503,
            content={
                "status": "RECOVERY_READ_ONLY",
                "issues": initial_issues or inspect(settings)["issues"],
                "next": "Use python -m adam.resilience.cli recovery locally",
            },
        )

    return app
