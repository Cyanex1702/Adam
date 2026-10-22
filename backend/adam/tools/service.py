import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import time
from collections.abc import Callable
from contextlib import closing, suppress
from pathlib import Path

from adam.core.contracts import Contract, new_id
from adam.core.privacy import contains_secret
from adam.observability.service import TraceService
from adam.security.policy import Principal
from adam.security.request import check_authority
from adam.tools.contracts import ToolCall, ToolResult
from adam.tools.registry import ToolError, ToolRegistry
from adam.tools.scope import FileScope


class Action(Contract):
    trace_id: str = ""
    action_id: str
    call: ToolCall
    digest: str
    before: dict[str, str]
    result: ToolResult
    approved_until: float = 0
    undo_of: str | None = None
    snapshot: str | None = None


class ActionService:
    """Explicit calls only. Model output never grants capabilities or approval."""

    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.scope = FileScope(data_dir / "tool-sandbox")
        self.registry = ToolRegistry()
        self.traces: TraceService | None = None
        self.path = data_dir / "actions.sqlite3"
        self.lock_path = data_dir / "actions-lock.sqlite3"
        self.readers: dict[str, Callable[[dict[str, object]], dict[str, object]]] = {}
        self.dispatcher: Callable[[str, str], None] = self.dispatch
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS actions("
                "id TEXT PRIMARY KEY, idem TEXT UNIQUE, record TEXT NOT NULL)"
            )
            db.execute("PRAGMA user_version=1")
        with closing(sqlite3.connect(self.lock_path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS mutex(id INTEGER PRIMARY KEY)")

    @staticmethod
    def permission(principal: Principal, *, elevated: bool = False) -> None:
        check_authority()
        if principal.mode != "owner" or not principal.authenticated or not principal.trusted_device:
            raise ToolError("TOOL.OWNER_REQUIRED")
        if elevated and not principal.elevated:
            raise ToolError("TOOL.REAUTHENTICATION_REQUIRED")

    def save(self, action: Action) -> None:
        raw = action.model_dump_json()
        if contains_secret(raw):
            raise ToolError("TOOL.SECRET_OUTPUT_DENIED")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO actions VALUES(?,?,?) ON CONFLICT(id) "
                "DO UPDATE SET record=excluded.record",
                (action.action_id, action.call.idempotency_key, raw),
            )
        if self.traces:
            with suppress(OSError, sqlite3.Error, ValueError):
                metadata = self.registry.metadata(action.call.name)
                self.traces.emit(
                    action.trace_id or action.action_id,
                    "tools",
                    action.call.name,
                    action.result.status,
                    error_code=action.result.error_code,
                    references=[action.action_id],
                    metrics={"risk_level": metadata.risk_level},
                )

    def get(self, identifier: str) -> Action:
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute(
                "SELECT record FROM actions WHERE id=? OR idem=?", (identifier, identifier)
            ).fetchone()
        if row is None:
            raise ToolError("TOOL.ACTION_NOT_FOUND")
        if contains_secret(row[0]):
            raise ToolError("TOOL.SECRET_OUTPUT_DENIED")
        action = Action.model_validate_json(row[0])
        if not action.trace_id:
            action.trace_id = action.action_id
        return action

    def list(self) -> list[Action]:
        with closing(sqlite3.connect(self.path)) as db, db:
            identifiers = db.execute(
                "SELECT id FROM actions ORDER BY rowid DESC LIMIT 100"
            ).fetchall()
        return [self.get(row[0]) for row in identifiers]

    def paths(self, call: ToolCall, internal: bool = False) -> dict[str, Path]:
        return {
            key: self.scope.path(str(value), internal=internal)
            for key, value in call.arguments.items()
            if key in {"path", "source", "destination"}
        }

    def preview(
        self,
        call: ToolCall,
        principal: Principal,
        *,
        undo_of: str | None = None,
        trace_id: str | None = None,
    ) -> Action:
        call = self.registry.validate(call)
        risk = self.registry.metadata(call.name).risk_level
        if risk >= 2:
            self.permission(principal)
        if call.name in {"apps.open", "files.open"} and os.name != "nt":
            raise ToolError("TOOL.DESKTOP_DISPATCH_UNAVAILABLE")
        try:
            existing = self.get(call.idempotency_key)
        except ToolError as exc:
            if exc.code != "TOOL.ACTION_NOT_FOUND":
                raise
        else:
            if existing.call != call:
                raise ToolError("TOOL.IDEMPOTENCY_CONFLICT")
            return existing
        before = {
            key: self.scope.stamp(path)
            for key, path in self.paths(call, undo_of is not None).items()
        }
        if call.name == "files.open" and (
            not before["path"].startswith("file:")
            or self.paths(call)["path"].suffix.lower() not in {".txt", ".md", ".pdf"}
        ):
            raise ToolError("TOOL.OPEN_TYPE_DENIED")
        if call.name in {"notes.create", "directories.create"} and before["path"] != "absent":
            raise ToolError("TOOL.DESTINATION_EXISTS")
        if call.name == "directories.remove_empty" and (
            self.paths(call)["path"] == self.scope.root
            or not before["path"].startswith("directory:")
            or any(self.paths(call)["path"].iterdir())
        ):
            raise ToolError("TOOL.EMPTY_DIRECTORY_REQUIRED")
        if call.name == "files.move" and (
            not before["source"].startswith("file:") or before["destination"] != "absent"
        ):
            raise ToolError("TOOL.MOVE_PRECONDITION")
        if call.name == "files.quarantine" and not before["path"].startswith("file:"):
            raise ToolError("TOOL.FILE_REQUIRED")
        identifier = new_id()
        digest = hashlib.sha256(
            json.dumps([call.model_dump(), before, str(self.scope.root)], sort_keys=True).encode()
        ).hexdigest()
        action = Action(
            trace_id=trace_id or identifier,
            action_id=identifier,
            call=call,
            digest=digest,
            before=before,
            undo_of=undo_of,
            result=ToolResult(action_id=identifier, status="PREVIEW", tool=call.name),
        )
        self.save(action)
        return action

    def approve(
        self, identifier: str, digest: str, principal: Principal, allow: bool = True
    ) -> Action:
        self.permission(principal, elevated=allow)
        action = self.get(identifier)
        if action.digest != digest or action.result.status != "PREVIEW":
            raise ToolError("TOOL.APPROVAL_MISMATCH")
        action.result.status = "APPROVED" if allow else "DENIED"
        action.approved_until = time.time() + 300 if allow else 0
        self.save(action)
        return action

    def execute(self, identifier: str, principal: Principal) -> Action:
        action = self.get(identifier)
        risk = self.registry.metadata(action.call.name).risk_level
        if risk >= 2:
            self.permission(principal, elevated=True)
        if action.result.status in {"VERIFIED", "UNDONE"}:
            return action
        if (
            risk >= 2
            and action.result.status != "RUNNING"
            and (action.result.status != "APPROVED" or action.approved_until < time.time())
        ):
            raise ToolError("TOOL.APPROVAL_REQUIRED")
        if risk < 2 and action.result.status not in {"PREVIEW", "RUNNING"}:
            raise ToolError("TOOL.ACTION_TERMINAL")
        try:
            with closing(sqlite3.connect(self.lock_path, timeout=0.1)) as lock, lock:
                lock.execute("BEGIN IMMEDIATE")
                action = self.get(identifier)
                if action.result.status in {"VERIFIED", "UNDONE"}:
                    return action
                if action.result.status == "RUNNING":
                    action.result.status = "UNCERTAIN"
                    action.result.epistemic_status = "UNCERTAIN"
                    action.result.error_code = "TOOL.RECOVERY_REVIEW_REQUIRED"
                    self.save(action)
                    return action
                if action.result.status not in {"PREVIEW", "APPROVED"}:
                    raise ToolError("TOOL.ACTION_TERMINAL")
                if risk >= 2 and (
                    action.result.status != "APPROVED" or action.approved_until < time.time()
                ):
                    raise ToolError("TOOL.APPROVAL_REQUIRED")
                paths = self.paths(action.call, action.undo_of is not None)
                if {key: self.scope.stamp(path) for key, path in paths.items()} != action.before:
                    raise ToolError("TOOL.STALE_PREVIEW")
                check_authority()
                action.result.status = "RUNNING"
                self.save(action)
                if action.call.name in {"files.move", "files.quarantine"}:
                    source = paths.get("source", paths.get("path"))
                    assert source is not None
                    snapshot = self.scope.path(
                        f".adam-snapshots/{action.action_id}/file", internal=True
                    )
                    snapshot.parent.mkdir(parents=True, exist_ok=False)
                    data = source.read_bytes()
                    with snapshot.open("xb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if snapshot.read_bytes() != data:
                        raise ToolError("TOOL.SNAPSHOT_FAILED")
                    action.snapshot = str(snapshot.relative_to(self.scope.root))
                    self.save(action)
                action.result.data = self.perform(action, paths)
                if contains_secret(json.dumps(action.result.data)):
                    raise ToolError("TOOL.SECRET_OUTPUT_DENIED")
                action.result.status = (
                    "DISPATCHED" if action.call.name in {"apps.open", "files.open"} else "VERIFIED"
                )
                if action.result.status == "DISPATCHED":
                    action.result.epistemic_status = "UNCERTAIN"
                self.save(action)
                if action.undo_of:
                    original = self.get(action.undo_of)
                    original.result.status = "UNDONE"
                    self.save(original)
        except sqlite3.OperationalError:
            raise ToolError("TOOL.RESOURCE_BUSY") from None
        except (ToolError, OSError, UnicodeError) as exc:
            action.result.status = (
                "UNCERTAIN" if risk >= 2 and action.result.status == "RUNNING" else "FAILED"
            )
            action.result.error_code = exc.code if isinstance(exc, ToolError) else "TOOL.IO_FAILED"
            action.result.epistemic_status = (
                "UNCERTAIN" if action.result.status == "UNCERTAIN" else "UNKNOWN"
            )
            self.save(action)
        return action

    def perform(self, action: Action, paths: dict[str, Path]) -> dict[str, object]:
        name, args = action.call.name, action.call.arguments
        if name in {"apps.open", "files.open"}:
            self.dispatcher(name, str(paths["path"]) if name == "files.open" else "notepad")
            return {"dispatch": "requested", "verification": "window_not_observed"}
        if name == "system.info":
            return {
                "system": platform.system(),
                "machine": platform.machine(),
                "cpu_count": os.cpu_count(),
            }
        if name == "files.search":
            return {
                "paths": self.scope.search(
                    str(args["directory"]), str(args["query"]), int(str(args["limit"]))
                )
            }
        if name in self.readers:
            return self.readers[name](args)
        if name == "files.read":
            path = paths["path"]
            if not self.scope.stamp(path).startswith("file:") or path.stat().st_size > 262144:
                raise ToolError("TOOL.TEXT_FILE_REQUIRED")
            return {"text": path.read_text(encoding="utf-8"), "stamp": self.scope.stamp(path)}
        if name == "notes.create":
            path = paths["path"]
            with path.open("xb") as stream:
                stream.write(str(args["text"]).encode())
                stream.flush()
                os.fsync(stream.fileno())
            if path.read_text(encoding="utf-8") != args["text"]:
                raise ToolError("TOOL.VERIFICATION_FAILED")
            return {"stamp": self.scope.stamp(path)}
        if name == "directories.create":
            paths["path"].mkdir()
            stamp = self.scope.stamp(paths["path"])
            if not stamp.startswith("directory:"):
                raise ToolError("TOOL.VERIFICATION_FAILED")
            return {"stamp": stamp}
        if name == "directories.remove_empty":
            paths["path"].rmdir()
            if paths["path"].exists():
                raise ToolError("TOOL.VERIFICATION_FAILED")
            return {"absent": True}
        if name in {"files.move", "files.quarantine"}:
            source = paths.get("source", paths.get("path"))
            assert source is not None
            destination = paths.get("destination")
            if destination is None:
                destination = self.scope.path(
                    f".adam-quarantine/{action.action_id}/file", internal=True
                )
                destination.parent.mkdir(parents=True, exist_ok=False)
            original = self.scope.stamp(source)
            # Hard link publication is atomic and refuses to overwrite existing destinations.
            os.link(source, destination)
            source.unlink()
            if self.scope.stamp(destination) != original or source.exists():
                raise ToolError("TOOL.VERIFICATION_FAILED")
            return {"stamp": original, "destination": str(destination.relative_to(self.scope.root))}
        raise ToolError("TOOL.EXECUTOR_UNAVAILABLE")

    @staticmethod
    def dispatch(name: str, value: str) -> None:
        if os.name != "nt":
            raise ToolError("TOOL.DESKTOP_DISPATCH_UNAVAILABLE")
        if name == "files.open":
            os.startfile(value)
        else:
            subprocess.Popen(
                [str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "notepad.exe")]
            )

    def undo(self, identifier: str, principal: Principal) -> Action:
        self.permission(principal)
        original = self.get(identifier)
        if original.result.status != "VERIFIED":
            raise ToolError("TOOL.UNDO_UNAVAILABLE")
        name, args = original.call.name, original.call.arguments
        if name == "notes.create":
            call = ToolCall(name="files.quarantine", arguments={"path": args["path"]})
            current = self.scope.path(str(args["path"]))
        elif name in {"files.move", "files.quarantine"}:
            destination = original.result.data["destination"]
            call = ToolCall(
                name="files.move",
                arguments={
                    "source": destination,
                    "destination": args.get("source", args.get("path")),
                },
            )
            current = self.scope.path(str(destination), internal=True)
        elif name == "directories.create":
            call = ToolCall(name="directories.remove_empty", arguments={"path": args["path"]})
            current = self.scope.path(str(args["path"]))
        else:
            raise ToolError("TOOL.UNDO_UNAVAILABLE")
        if self.scope.stamp(current) != original.result.data["stamp"]:
            raise ToolError("TOOL.UNDO_CONFLICT")
        return self.preview(call, principal, undo_of=identifier)
