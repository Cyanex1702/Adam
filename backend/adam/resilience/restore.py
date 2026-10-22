import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from adam.core.config import Settings
from adam.core.contracts import new_id, utc_now
from adam.core.migrations import migrate
from adam.knowledge.contracts import SourceRecord
from adam.resilience.archive import DB_PATHS, BackupService, no_link, safe_name, scoped
from adam.resilience.contracts import BackupError
from adam.resilience.recovery import inspect
from adam.security.request import check_authority
from adam.tasks.service import Task
from adam.tools.service import Action


class RestoreService:
    def restore(
        self, archive: Path, password: str, target: Path, *, restore_vault: bool = False
    ) -> dict[str, object]:
        manifest, files = BackupService.read(archive, password)
        no_link(target)
        for parent in target.parents:
            no_link(parent)
        destination = target.expanduser().resolve()
        if destination.exists():
            raise BackupError("RESTORE.FRESH_TARGET_REQUIRED")
        if restore_vault and not manifest.vault_included:
            raise BackupError("RESTORE.VAULT_NOT_INCLUDED")
        if not destination.name or destination == destination.parent:
            raise BackupError("RESTORE.TARGET_INVALID")
        destination.parent.mkdir(parents=True, exist_ok=True)
        published = False
        try:
            with TemporaryDirectory(prefix=".adam-restore-", dir=destination.parent) as temporary:
                stage = Path(temporary).resolve()
                # Both targets remain within the explicitly chosen parent. No active
                # directory can be replaced; rename is the final publication step.
                if not stage.is_relative_to(destination.parent):
                    raise BackupError("RESTORE.TARGET_INVALID")
                for name in manifest.directories:
                    scoped(stage, name).mkdir(parents=True, exist_ok=True)
                for name, data in files.items():
                    if name == "security/vault.sqlite3" and not restore_vault:
                        continue
                    if not safe_name(name):
                        raise BackupError("BACKUP.PATH_DENIED")
                    path = scoped(stage, name)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("xb") as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                config = Settings.model_validate_json(files["config/settings.json"])
                config.data_dir = destination
                config.identity_dir = destination / "identity"
                config.knowledge.allowed_roots = [destination / "knowledge/restored-sources"]
                migrate(stage / "runtime.sqlite3")
                self.reset(stage)
                rebound = self.rebind_sources(stage, destination)
                # Saved settings are deliberately rebound only for portable data paths.
                saved = stage / "config/restored-settings.json"
                saved.write_text(config.model_dump_json(indent=2), encoding="utf-8", newline="\n")
                verification = inspect(
                    config.model_copy(
                        update={"data_dir": stage, "identity_dir": stage / "identity"}
                    )
                )
                if verification["mode"] != "HEALTHY":
                    raise BackupError("RESTORE.VERIFICATION_FAILED")
                report = {
                    "status": "VERIFIED",
                    "created_at": utc_now().isoformat(),
                    "identity_digest": manifest.identity_digest,
                    "source_release": manifest.release,
                    "vault_restored": restore_vault,
                    "sources_rebound": rebound,
                    "indexes": "NOT_RESTORED_REBUILD_OR_KEYWORD",
                    "sessions_and_approvals": "REVOKED",
                    "target": str(destination),
                }
                (stage / "config/restore-receipt.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8", newline="\n"
                )
                check_authority()
                if destination.exists():
                    raise BackupError("RESTORE.FRESH_TARGET_REQUIRED")
                stage.rename(destination)
                published = True
                return report
        except (sqlite3.Error, OSError, ValueError) as error:
            if isinstance(error, BackupError):
                raise
            raise BackupError("RESTORE.IO_OR_STATE_FAILED") from None
        finally:
            # TemporaryDirectory cleans only the private staging directory. A published
            # target is retained; no recursive deletion touches destination/owner data.
            if published and not destination.is_dir():
                raise BackupError("RESTORE.PUBLICATION_FAILED")

    @staticmethod
    def reset(stage: Path) -> None:
        with closing(sqlite3.connect(stage / "runtime.sqlite3")) as db, db:
            db.execute("UPDATE sessions SET lease_owner=NULL,lease_until=0")
            # Training consent is local to a session/device; examples remain reviewable.
            db.execute("DELETE FROM training_settings")
        auth = stage / "security/auth.sqlite3"
        if auth.exists():
            with closing(sqlite3.connect(auth)) as db, db:
                db.execute("DELETE FROM tokens")
        actions = stage / "actions.sqlite3"
        if actions.exists():
            with closing(sqlite3.connect(actions)) as db, db:
                for identifier, raw in db.execute("SELECT id,record FROM actions").fetchall():
                    action = Action.model_validate_json(raw)
                    action.approved_until = 0
                    if action.result.status in {"PREVIEW", "APPROVED", "RUNNING"}:
                        action.result.status = "UNCERTAIN"
                        action.result.error_code = "TOOL.RESTORE_REVIEW_REQUIRED"
                    action.result.epistemic_status = (
                        "REPORTED"
                        if action.result.status in {"VERIFIED", "UNDONE"}
                        else "UNCERTAIN"
                    )
                    db.execute(
                        "UPDATE actions SET record=? WHERE id=?",
                        (action.model_dump_json(), identifier),
                    )
        tasks = stage / "tasks.sqlite3"
        if tasks.exists():
            with closing(sqlite3.connect(tasks)) as db, db:
                for identifier, raw in db.execute("SELECT id,record FROM tasks").fetchall():
                    task = Task.model_validate_json(raw)
                    task.approved_until = 0
                    if task.status not in {"COMPLETED", "CANCELLED", "PARTIALLY_COMPLETED"}:
                        task.status, task.error_code = "PAUSED", "TASK.RESTORE_REVIEW_REQUIRED"
                    for step in task.plan.steps:
                        if step.status == "RUNNING":
                            step.status = "UNCERTAIN"
                    db.execute(
                        "UPDATE tasks SET record=? WHERE id=?", (task.model_dump_json(), identifier)
                    )

    @staticmethod
    def rebind_sources(stage: Path, destination: Path) -> int:
        count = 0
        with closing(sqlite3.connect(stage / "runtime.sqlite3")) as db, db:
            db.execute("DELETE FROM knowledge_paths")
            for (raw,) in db.execute("SELECT record FROM knowledge_sources").fetchall():
                source = SourceRecord.model_validate_json(raw)
                blob = scoped(stage, f"knowledge/blobs/{source.content_hash}.bin")
                if not blob.is_file():
                    source.status = "MISSING"
                else:
                    import hashlib

                    suffix = ".pdf" if source.media_type == "application/pdf" else ".txt"
                    name = hashlib.sha256(source.source_id.encode()).hexdigest() + suffix
                    copied = stage / "knowledge/restored-sources" / name
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    copied.write_bytes(blob.read_bytes())
                    source.path = str(destination / "knowledge/restored-sources" / name)
                    count += 1
                db.execute(
                    "UPDATE knowledge_sources SET status=?,record=? WHERE source_id=?",
                    (source.status, source.model_dump_json(), source.source_id),
                )
                db.execute(
                    "INSERT INTO knowledge_paths VALUES (?,?,?,?)",
                    (source.path, source.namespace, source.source_id, source.status),
                )
        return count


def rebuild_indexes(settings: Settings) -> dict[str, object]:
    """Explicit offline operation; preserve a broken derived index, never core data."""
    if inspect(settings)["mode"] != "HEALTHY":
        raise BackupError("RECOVERY.READ_ONLY")
    import portalocker

    from adam.core.storage import ConversationStore
    from adam.knowledge.retrieval import RetrievalService
    from adam.knowledge.service import KnowledgeService

    vectors = scoped(settings.data_dir, "knowledge/vectors")
    quarantined: Path | None = None
    if vectors.exists():
        try:
            with portalocker.Lock(str(vectors / ".lock"), mode="a+b", timeout=0):
                pass
        except portalocker.exceptions.LockException:
            raise BackupError("RESTORE.INDEX_BUSY") from None
        quarantined = vectors.with_name("vectors-quarantine-" + new_id())
        vectors.rename(quarantined)
    receipt = scoped(settings.data_dir, "knowledge/index-receipt.json")
    if receipt.exists():
        receipt.rename(receipt.with_name("index-receipt-quarantine-" + new_id() + ".json"))
    retrieval = RetrievalService(
        KnowledgeService(ConversationStore(settings.data_dir / DB_PATHS[0]), settings.knowledge)
    )
    try:
        result = retrieval.reindex()
        result["quarantined_previous_index"] = quarantined is not None
        return result
    finally:
        retrieval.close()
