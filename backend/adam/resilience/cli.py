import argparse
import getpass
import json
import os
import sqlite3
from pathlib import Path

from adam.core.config import Settings, load_settings, resolve_data_dir
from adam.core.privacy import contains_secret
from adam.resilience.archive import BackupService
from adam.resilience.contracts import BackupError
from adam.resilience.export import ExportFilter, ExportService
from adam.resilience.recovery import RecoveryService, inspect
from adam.resilience.restore import RestoreService, rebuild_indexes
from adam.security.auth import AuthError, AuthManager


def settings_for(directory: Path | None, recovery: bool = False) -> Settings:
    environment = dict(os.environ)
    if directory:
        environment.pop("ADAM_CONFIG", None)
        environment["ADAM_DATA_DIR"] = str(directory.resolve())
    try:
        return load_settings(env=environment)
    except (ValueError, OSError):
        if not recovery:
            raise BackupError("CONFIG.INVALID") from None
        return Settings(data_dir=resolve_data_dir(environment))


def owner(settings: Settings) -> None:
    auth = AuthManager(settings.data_dir)
    credential = getpass.getpass("Owner passphrase (hidden): ")
    try:
        auth.verify(credential)
    finally:
        credential = ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ADAM local backup, isolated restore and read-only recovery"
    )
    parser.add_argument(
        "--data-dir", type=Path, help="Choose a store; restored settings load automatically"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument(
        "--generation", choices=["daily", "weekly", "monthly", "milestone"], default="daily"
    )
    backup.add_argument("--include-vault", action="store_true")
    verify = commands.add_parser("verify")
    verify.add_argument("archive", type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("archive", type=Path)
    restore.add_argument("target", type=Path, help="Must not already exist")
    restore.add_argument("--restore-vault", action="store_true")
    recovery = commands.add_parser("recovery")
    recovery.add_argument("--table", choices=["memories", "sessions", "knowledge_sources"])
    recovery.add_argument("--limit", type=int, default=100)
    commands.add_parser("rebuild-index")
    export = commands.add_parser("export")
    export.add_argument(
        "target", type=Path, help="New directory for human-readable cleartext files"
    )
    export.add_argument(
        "--section",
        action="append",
        choices=["memories", "conversations", "knowledge", "tasks", "actions"],
    )
    export.add_argument("--format", action="append", choices=["json", "jsonl", "markdown", "csv"])
    export.add_argument("--person")
    export.add_argument("--project")
    export.add_argument("--since")
    export.add_argument("--until")
    export.add_argument(
        "--memory-type", choices=["semantic", "episodic", "preference", "project", "goal"]
    )
    export.add_argument("--conversation-id")
    export.add_argument("--task-id")
    export.add_argument(
        "--recovery",
        action="store_true",
        help="Local OS-trusted read-only salvage; partial results are marked",
    )
    export.add_argument("--max-records", type=int, default=10000)
    args = parser.parse_args()
    password = ""
    try:
        settings = settings_for(
            args.data_dir, args.command == "recovery" or args.command == "export" and args.recovery
        )
        if args.command == "recovery":
            service = RecoveryService(settings)
            result = service.status()
            result["session_mode"] = "RECOVERY_READ_ONLY"
            if args.table:
                result["records"] = [
                    row
                    for row in service.records(args.table, args.limit)
                    if not contains_secret(json.dumps(row))
                ]
        elif args.command == "export":
            if not args.recovery:
                if inspect(settings)["mode"] != "HEALTHY":
                    raise BackupError("RECOVERY.READ_ONLY")
                owner(settings)
            raw = {
                "person": args.person,
                "project": args.project,
                "since": args.since,
                "until": args.until,
                "memory_type": args.memory_type,
                "conversation_id": args.conversation_id,
                "task_id": args.task_id,
                "max_records": args.max_records,
            }
            if args.section:
                raw["sections"] = args.section
            if args.format:
                raw["formats"] = args.format
            selection = ExportFilter.model_validate(raw)
            result = ExportService(settings).export(args.target, selection, recovery=args.recovery)
        elif args.command == "rebuild-index":
            if inspect(settings)["mode"] != "HEALTHY":
                raise BackupError("RECOVERY.READ_ONLY")
            owner(settings)
            result = rebuild_indexes(settings)
        else:
            if args.command == "backup":
                if inspect(settings)["mode"] != "HEALTHY":
                    raise BackupError("RECOVERY.READ_ONLY")
                owner(settings)
            password = getpass.getpass("Backup passphrase (hidden, 12+ characters): ")
            if args.command == "backup":
                confirm = getpass.getpass("Confirm backup passphrase: ")
                if password != confirm:
                    raise BackupError("BACKUP.PASSPHRASE_MISMATCH")
                confirm = ""
                receipt = BackupService(settings).create(
                    password, generation=args.generation, include_vault=args.include_vault
                )
                result = {
                    **receipt.model_dump(),
                    "path": str(BackupService(settings).path(receipt.backup_id)),
                }
            elif args.command == "verify":
                manifest, _ = BackupService.read(args.archive, password)
                result = {
                    "status": "VERIFIED",
                    "files": len(manifest.files),
                    "schemas": manifest.schemas,
                    "vault_included": manifest.vault_included,
                }
            else:
                result = RestoreService().restore(
                    args.archive, password, args.target, restore_vault=args.restore_vault
                )
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (BackupError, AuthError) as error:
        print(json.dumps({"status": "FAILED", "error": error.code}))
        raise SystemExit(1) from None
    except (OSError, sqlite3.Error):
        print(json.dumps({"status": "FAILED", "error": "MAINTENANCE.IO_FAILED"}))
        raise SystemExit(1) from None
    except ValueError:
        print(json.dumps({"status": "FAILED", "error": "MAINTENANCE.INPUT_INVALID"}))
        raise SystemExit(1) from None
    finally:
        password = ""


if __name__ == "__main__":
    main()
