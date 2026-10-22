import csv
import io
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from adam.core.config import Settings
from adam.core.contracts import Contract, utc_now
from adam.core.privacy import contains_secret, safe_transcript
from adam.knowledge.contracts import SourcePolicy, SourceRecord
from adam.memory.consolidation import Candidate
from adam.memory.service import MemoryRecord, normalize
from adam.resilience.archive import digest, no_link, scoped
from adam.resilience.contracts import BackupError
from adam.resilience.recovery import inspect, recovery_readonly
from adam.security.policy import Principal, ResourcePolicy, decide
from adam.security.request import check_authority
from adam.tasks.service import Task
from adam.tools.service import Action

Section = Literal["memories", "conversations", "knowledge", "tasks", "actions"]
Format = Literal["json", "jsonl", "markdown", "csv"]
MAX_EXPORT_BYTES = 32 * 1024 * 1024


def default_sections() -> list[Section]:
    return ["memories", "conversations", "knowledge", "tasks", "actions"]


def default_formats() -> list[Format]:
    return ["json", "jsonl", "markdown", "csv"]


class ExportFilter(Contract):
    sections: list[Section] = Field(
        default_factory=default_sections,
        min_length=1,
        max_length=5,
    )
    formats: list[Format] = Field(default_factory=default_formats, min_length=1, max_length=4)
    person: str | None = Field(default=None, min_length=1, max_length=128)
    project: str | None = Field(default=None, min_length=1, max_length=100)
    since: datetime | None = None
    until: datetime | None = None
    memory_type: Literal["semantic", "episodic", "preference", "project", "goal"] | None = None
    conversation_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")
    task_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")
    max_records: int = Field(default=10000, ge=1, le=100000)

    @field_validator("since", "until", mode="before")
    @classmethod
    def dates(cls, value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, str) and len(value) == 10:
            day = datetime.strptime(value, "%Y-%m-%d").date()
            return datetime.combine(day, time.max if info.field_name == "until" else time.min, UTC)
        return value

    @field_validator("since", "until")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value

    @model_validator(mode="after")
    def valid(self) -> "ExportFilter":
        if self.since and self.until and self.since > self.until:
            raise ValueError("EXPORT.DATE_RANGE_INVALID")
        if self.task_id:
            self.sections = [
                section for section in self.sections if section in {"tasks", "actions"}
            ]
        if self.conversation_id:
            self.sections = [
                section for section in self.sections if section in {"memories", "conversations"}
            ]
        if self.memory_type:
            self.sections = [section for section in self.sections if section == "memories"]
        if not self.sections or contains_secret(self.model_dump_json()):
            raise ValueError("EXPORT.FILTER_INVALID")
        self.sections = list(dict.fromkeys(self.sections))
        self.formats = list(dict.fromkeys(self.formats))
        return self

    def date_matches(self, timestamp: str | float | None) -> bool:
        if not self.since and not self.until:
            return True
        if timestamp is None:
            return False
        date = (
            datetime.fromtimestamp(timestamp, UTC)
            if isinstance(timestamp, float)
            else datetime.fromisoformat(timestamp)
        )
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        return not ((self.since and date < self.since) or (self.until and date > self.until))


def allowed(record: MemoryRecord | SourceRecord) -> bool:
    item: MemoryRecord | SourcePolicy = (
        record.policy if isinstance(record, SourceRecord) else record
    )
    sensitivity = record.policy.sensitivity if isinstance(record, SourceRecord) else record.privacy
    return decide(
        Principal(),
        ResourcePolicy(
            sensitivity=sensitivity,
            allowed_audiences=item.allowed_audiences,
            subjects=item.subjects,
            disclosure_owner=item.disclosure_owner,
            source_actor="local_owner_export",
            profile=item.profile,
        ),
    ).allowed


def label_matches(project: str | None, label: str) -> bool:
    return (
        project is None
        or normalize(label) == normalize(project)
        or normalize(label).startswith(normalize(project) + " ")
    )


class ExportService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def collect(self, selection: ExportFilter, *, recovery: bool = False) -> dict[str, Any]:
        selection = ExportFilter.model_validate(selection.model_dump())
        health = inspect(self.settings)
        if not recovery and health["mode"] != "HEALTHY":
            raise BackupError("RECOVERY.READ_ONLY")
        records: dict[str, list[dict[str, Any]]] = {section: [] for section in selection.sections}
        omitted = {"credential_or_policy": 0, "invalid_record": 0}
        statuses: dict[str, str] = {}
        related_sessions: set[str] = set()
        related_actions: set[str] = set()
        count = 0
        scanned = 0

        def rows(database: str, section: str, query: str) -> list[sqlite3.Row]:
            nonlocal scanned
            try:
                path = scoped(self.settings.data_dir, database)
                if not path.exists():
                    statuses[section] = "ABSENT"
                    return []
                with closing(recovery_readonly(path)) as db:
                    db.row_factory = sqlite3.Row
                    db.execute("PRAGMA query_only=ON")
                    found = db.execute(query).fetchmany(100001)
                    scanned += len(found)
                    if scanned > 100000:
                        raise BackupError("EXPORT.SCAN_LIMIT")
                    statuses[section] = "READABLE"
                    return found
            except (sqlite3.Error, OSError, BackupError) as error:
                if (
                    not recovery
                    or isinstance(error, BackupError)
                    and error.code == "EXPORT.SCAN_LIMIT"
                ):
                    if isinstance(error, BackupError):
                        raise
                    raise BackupError("EXPORT.STORE_UNREADABLE") from None
                statuses[section] = "UNREADABLE"
                return []

        def add(section: str, record: dict[str, Any]) -> None:
            nonlocal count
            if contains_secret(json.dumps(record, ensure_ascii=False)):
                omitted["credential_or_policy"] += 1
                return
            if section not in records:
                return
            count += 1
            if count > selection.max_records:
                raise BackupError("EXPORT.RECORD_LIMIT")
            records[section].append(record)

        if "memories" in records or selection.project:
            for row in rows(
                "runtime.sqlite3", "memories", "SELECT record FROM memories ORDER BY rowid"
            ):
                try:
                    memory = MemoryRecord.model_validate_json(row[0])
                    if not allowed(memory) or contains_secret(memory.model_dump_json()):
                        omitted["credential_or_policy"] += 1
                        continue
                    if selection.person and selection.person not in {
                        memory.disclosure_owner,
                        *memory.subjects,
                    }:
                        continue
                    if selection.project and (
                        memory.type != "project" or not label_matches(selection.project, memory.key)
                    ):
                        continue
                    if selection.memory_type and memory.type != selection.memory_type:
                        continue
                    if selection.conversation_id and not any(
                        item.session_id == selection.conversation_id for item in memory.provenance
                    ):
                        continue
                    if not selection.date_matches(memory.created_at.isoformat()):
                        continue
                    related_sessions.update(item.session_id for item in memory.provenance)
                    add("memories", {"record_type": "memory", **memory.model_dump(mode="json")})
                except BackupError:
                    raise
                except ValueError:
                    omitted["invalid_record"] += 1

            if "memories" in records and not selection.project:
                for row in rows(
                    "runtime.sqlite3",
                    "memory_candidates",
                    "SELECT record FROM memory_candidates ORDER BY rowid",
                ):
                    try:
                        candidate = Candidate.model_validate_json(row[0])
                        if (
                            selection.person not in {None, "owner"}
                            or selection.memory_type
                            and candidate.type != selection.memory_type
                            or selection.conversation_id
                            and candidate.evidence.session_id != selection.conversation_id
                            or not selection.date_matches(candidate.evidence.timestamp.isoformat())
                        ):
                            continue
                        add(
                            "memories",
                            {"record_type": "candidate", **candidate.model_dump(mode="json")},
                        )
                    except BackupError:
                        raise
                    except ValueError:
                        omitted["invalid_record"] += 1

        if "conversations" in records:
            for row in rows(
                "runtime.sqlite3",
                "conversations",
                "SELECT turn_id,session_id,user_text,assistant_text,created_at,trace_id,model_id "
                "FROM turns ORDER BY turn_id",
            ):
                try:
                    if (
                        selection.person not in {None, "owner"}
                        or selection.project
                        and row["session_id"] not in related_sessions
                        or selection.conversation_id
                        and row["session_id"] != selection.conversation_id
                        or not selection.date_matches(row["created_at"])
                    ):
                        continue
                    item = dict(row)
                    item["person_id"] = "owner"
                    item["user_text"] = safe_transcript(item["user_text"])
                    item["assistant_text"] = safe_transcript(item["assistant_text"])
                    item["provenance"] = {
                        "source": "conversation_archive",
                        "assistant_status": "UNVERIFIED",
                        "trace_id": item["trace_id"],
                    }
                    add("conversations", item)
                except BackupError:
                    raise
                except ValueError:
                    omitted["invalid_record"] += 1

        if "knowledge" in records:
            for row in rows(
                "runtime.sqlite3",
                "knowledge",
                "SELECT record FROM knowledge_sources ORDER BY rowid",
            ):
                try:
                    source = SourceRecord.model_validate_json(row[0])
                    if not allowed(source):
                        omitted["credential_or_policy"] += 1
                        continue
                    if (
                        selection.person
                        and selection.person
                        not in {source.policy.disclosure_owner, *source.policy.subjects}
                        or selection.project
                        and source.namespace != selection.project
                        or not selection.date_matches(source.ingested_at.isoformat())
                    ):
                        continue
                    # Metadata export, not an implicit disclosure of full document bodies.
                    add("knowledge", source.model_dump(mode="json"))
                except BackupError:
                    raise
                except ValueError:
                    omitted["invalid_record"] += 1

        if "tasks" in records or "actions" in records and (selection.project or selection.task_id):
            for row in rows("tasks.sqlite3", "tasks", "SELECT record FROM tasks ORDER BY rowid"):
                try:
                    task = Task.model_validate_json(row[0])
                    if (
                        selection.person
                        and task.created_by != selection.person
                        or selection.task_id
                        and task.task_id != selection.task_id
                        or not label_matches(selection.project, task.plan.goal)
                        or not selection.date_matches(task.created_at)
                    ):
                        continue
                    if contains_secret(task.model_dump_json()):
                        omitted["credential_or_policy"] += 1
                        continue
                    related_actions.update(
                        step.action_id for step in task.plan.steps if step.action_id
                    )
                    add("tasks", task.model_dump(mode="json"))
                except BackupError:
                    raise
                except ValueError:
                    omitted["invalid_record"] += 1

        if "actions" in records:
            for row in rows(
                "actions.sqlite3", "actions", "SELECT record FROM actions ORDER BY rowid"
            ):
                try:
                    action = Action.model_validate_json(row[0])
                    if (
                        selection.person not in {None, "owner"}
                        or (selection.project or selection.task_id)
                        and action.action_id not in related_actions
                        or not selection.date_matches(None)
                    ):
                        continue
                    item = action.model_dump(mode="json")
                    item["timestamp_status"] = "NOT_RECORDED_BY_ACTION_JOURNAL"
                    add("actions", item)
                except BackupError:
                    raise
                except ValueError:
                    omitted["invalid_record"] += 1
        partial = (
            any(status == "UNREADABLE" for status in statuses.values())
            or omitted["invalid_record"] > 0
        )
        return {
            "format": 1,
            "created_at": utc_now().isoformat(),
            "status": "PARTIAL" if partial else "COMPLETE",
            "recovery": recovery,
            "filters": selection.model_dump(mode="json"),
            "section_status": statuses,
            "omitted": omitted,
            "counts": {name: len(values) for name, values in records.items()},
            "records": records,
            "note": "Owner store only. Vault/auth, working instructions, source bodies and "
            "profile stores are excluded. Actions without recorded timestamps are omitted from "
            "date-filtered exports. Project labels use project memory keys, namespaces and "
            "task-goal prefixes; conversations follow memory provenance.",
        }

    def export(
        self, target: Path, selection: ExportFilter | None = None, *, recovery: bool = False
    ) -> dict[str, Any]:
        filters = selection or ExportFilter()
        bundle = self.collect(filters, recovery=recovery)
        payloads = render(bundle, filters.formats)
        if sum(len(data) for data in payloads.values()) > MAX_EXPORT_BYTES:
            raise BackupError("EXPORT.SIZE_LIMIT")
        no_link(target)
        for parent in target.parents:
            no_link(parent)
        destination = target.expanduser().resolve()
        if destination.exists():
            raise BackupError("EXPORT.FRESH_TARGET_REQUIRED")
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            key: bundle[key]
            for key in [
                "created_at",
                "status",
                "recovery",
                "counts",
                "filters",
                "section_status",
                "omitted",
                "note",
            ]
        }
        manifest["files"] = {
            name: {"sha256": digest(data), "size": len(data)} for name, data in payloads.items()
        }
        payloads["export-manifest.json"] = json.dumps(
            manifest, ensure_ascii=False, indent=2
        ).encode()
        try:
            with TemporaryDirectory(prefix=".adam-export-", dir=destination.parent) as temporary:
                stage = Path(temporary).resolve()
                if not stage.is_relative_to(destination.parent):
                    raise BackupError("EXPORT.PATH_DENIED")
                for name, data in payloads.items():
                    path = stage / name
                    with path.open("xb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    if path.read_bytes() != data:
                        raise BackupError("EXPORT.VERIFY_FAILED")
                check_authority()
                if destination.exists():
                    raise BackupError("EXPORT.FRESH_TARGET_REQUIRED")
                stage.rename(destination)
            return {**manifest, "target": str(destination), "integrity": "VERIFIED"}
        except OSError:
            raise BackupError("EXPORT.IO_FAILED") from None


def render(bundle: dict[str, Any], formats: list[Format]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
    if contains_secret(encoded):
        raise BackupError("EXPORT.CREDENTIAL_BLOCKED")
    if "json" in formats:
        result["data.json"] = encoded.encode()
    entries = [
        {"section": section, "record": item}
        for section, records in bundle["records"].items()
        for item in records
    ]
    if "jsonl" in formats:
        metadata = {key: value for key, value in bundle.items() if key != "records"}
        result["data.jsonl"] = (
            "\n".join(
                json.dumps(item, ensure_ascii=False)
                for item in [{"section": "export_metadata", "record": metadata}, *entries]
            )
            + "\n"
        ).encode()
    if "markdown" in formats:
        lines = [
            "# ADAM personal data export",
            "",
            f"Status: {bundle['status']}",
            "",
            "Original provenance and epistemic status are preserved. "
            "Assistant replies remain unverified.",
            "",
        ]
        for section, records in bundle["records"].items():
            lines.extend(
                [
                    f"## {section} ({len(records)})",
                    "",
                    "```json",
                    json.dumps(records, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
        result["summary.md"] = "\n".join(lines).encode()
    if "csv" in formats:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(["section", "record_id", "created_at", "provenance", "record_json"])
        for entry in entries:
            item = entry["record"]
            identifier = next(
                (
                    item[key]
                    for key in ["memory_id", "turn_id", "source_id", "task_id", "action_id"]
                    if key in item
                ),
                "",
            )
            cells = [
                entry["section"],
                str(identifier),
                str(item.get("created_at", item.get("ingested_at", ""))),
                json.dumps(item.get("provenance", {}), ensure_ascii=False),
                json.dumps(item, ensure_ascii=False),
            ]
            writer.writerow(
                [
                    "'" + cell
                    if (
                        cell.lstrip().startswith(("=", "+", "-", "@"))
                        or cell.startswith(("\t", "\r", "\n"))
                    )
                    else cell
                    for cell in cells
                ]
            )
        result["records.csv"] = stream.getvalue().encode()
    return result
