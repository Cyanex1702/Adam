import sqlite3
from contextlib import closing
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from adam import APP_VERSION
from adam.core.config import Settings
from adam.identity.service import IdentityService
from adam.resilience.archive import DB_PATHS, check_db, scoped
from adam.resilience.contracts import BackupError


def recovery_readonly(path: Path) -> sqlite3.Connection:
    wal = path.with_name(path.name + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise BackupError("RECOVERY.WAL_ACTIVE_CLOSE_WRITERS_FIRST")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


def inspect(settings: Settings) -> dict[str, object]:
    """No initialization, migrations, lock files, writes or model calls."""
    issues: list[str] = []
    stores: dict[str, str] = {}
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
                check_db(db, name)
            stores[name] = "HEALTHY"
        except (BackupError, sqlite3.Error, OSError) as error:
            code = error.code if isinstance(error, BackupError) else "STORAGE.INTEGRITY_FAILED"
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
    return {
        "mode": "RECOVERY_READ_ONLY" if issues else "HEALTHY",
        "issues": sorted(set(issues)),
        "stores": stores,
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
