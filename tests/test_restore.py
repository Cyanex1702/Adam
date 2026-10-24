import asyncio
import json
import sqlite3
from contextlib import closing

import portalocker
import pytest
from adam.api.app import create_app
from adam.core.config import load_settings
from adam.core.runtime import ChatRequest, Runtime
from adam.evals.suite import ProbeProvider
from adam.knowledge.contracts import SourceRequest
from adam.knowledge.retrieval import QueryRequest
from adam.models.llama_cpp import LlamaCppProvider
from adam.resilience.archive import BackupService, digest
from adam.resilience.cli import main
from adam.resilience.contracts import BackupError
from adam.resilience.recovery import RecoveryService, inspect
from adam.resilience.restore import RestoreService, rebuild_indexes
from adam.security.policy import Principal
from adam.security.vault import Vault
from adam.tools.contracts import ToolCall
from fastapi.testclient import TestClient
from test_backup import OWNER, PASSWORD, seeded


def contents(root):
    return {
        path.relative_to(root).as_posix(): digest(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }


def test_restore_preserves_state_rebinds_sources_and_revokes_capabilities_without_llm(tmp_path):
    root = tmp_path / "source"
    settings, runtime, auth, token = seeded(root)
    settings.recent_turns = 17
    settings.model.temperature = 0.23
    settings.knowledge.allowed_roots = [root]
    settings.knowledge.embedding_dir = root / "missing-public-embedding"
    runtime.knowledge.config = settings.knowledge
    source = root / "cedar.md"
    source.write_text("Fictional Cedar command: cedar serve --port 9123.\n", encoding="utf-8")
    runtime.knowledge.ingest(SourceRequest(path=str(source)))
    (root / "tool-sandbox/empty-folder").mkdir()
    pending = runtime.actions.preview(
        ToolCall(name="notes.create", arguments={"path": "pending.txt", "text": "pending fixture"}),
        Principal(),
    )
    runtime.actions.approve(pending.action_id, pending.digest, Principal(elevated=True))
    task = runtime.tasks.create(runtime.tasks.planner.from_goal("diagnose ."), Principal())
    runtime.tasks.approve(task.task_id, task.digest, Principal(elevated=True))
    service = BackupService(settings)
    receipt = service.create(PASSWORD)
    asyncio.run(runtime.chat(ChatRequest(text="/correct editor = ChangedAfterSnapshot")))
    before = contents(root)
    target = tmp_path / "restored"
    result = RestoreService().restore(service.path(receipt.backup_id), PASSWORD, target)
    assert result["status"] == "VERIFIED" and result["sources_rebound"] == 1
    assert contents(root) == before
    restored_settings = load_settings(env={"ADAM_DATA_DIR": str(target)})
    assert restored_settings.recent_turns == 17 and restored_settings.model.temperature == 0.23
    assert restored_settings.identity_dir == target / "identity"
    assert inspect(restored_settings)["mode"] == "HEALTHY"
    unavailable_model = restored_settings.model.model_copy(
        update={"base_url": "http://127.0.0.1:1", "timeout_seconds": 0.1}
    )
    restored = Runtime(restored_settings, LlamaCppProvider(unavailable_model))
    assert restored.identity.digest == runtime.identity.digest
    assert restored.memories.search("editor")[0].content == "SnapshotStudio"
    assert runtime.memories.search("editor")[0].content == "ChangedAfterSnapshot"
    assert restored.actions.get(pending.action_id).approved_until == 0
    assert restored.actions.get(pending.action_id).result.status == "UNCERTAIN"
    assert restored.tasks.get(task.task_id).status == "PAUSED"
    assert not (target / "tool-sandbox/pending.txt").exists()
    assert (target / "tool-sandbox/empty-folder").is_dir()
    with closing(sqlite3.connect(target / "security/auth.sqlite3")) as db:
        assert db.execute("SELECT COUNT(*) FROM tokens").fetchone()[0] == 0
    assert auth.resolve(token).mode == "owner"
    evidence = restored.retrieval.search(QueryRequest(query="Cedar command"))
    assert evidence.evidence and evidence.evidence[0].source.path.startswith(str(target))
    result = asyncio.run(restored.chat(ChatRequest(text="/show memory editor")))
    assert result.event_type == "agent.completed" and "SnapshotStudio" in str(result.payload)
    restored.retrieval.close()
    runtime.retrieval.close()


def test_restore_refuses_existing_targets_and_leaves_no_partial_output(tmp_path, monkeypatch):
    settings, runtime, _, _ = seeded(tmp_path / "source")
    service = BackupService(settings)
    receipt = service.create(PASSWORD)
    target = tmp_path / "existing"
    target.mkdir()
    note = target / "precious.txt"
    note.write_text("keep this synthetic fixture")
    with pytest.raises(BackupError, match="FRESH_TARGET_REQUIRED"):
        RestoreService().restore(service.path(receipt.backup_id), PASSWORD, target)
    assert note.read_text() == "keep this synthetic fixture"
    from pathlib import Path

    monkeypatch.setattr(Path, "rename", lambda *args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(BackupError, match="IO_OR_STATE_FAILED"):
        RestoreService().restore(service.path(receipt.backup_id), PASSWORD, tmp_path / "failed")
    assert not (tmp_path / "failed").exists() and not list(tmp_path.glob(".adam-restore-*"))
    runtime.retrieval.close()


def test_vault_is_opt_in_at_backup_and_restore(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path / "source")
    vault = Vault(settings.data_dir, "fernet")
    principal = Principal(elevated=True)
    vault.unlock(principal, "synthetic-vault-passphrase-148726")
    handle = vault.put(principal, "fixture", "synthetic-restore-value-5938")
    service = BackupService(settings)
    receipt = service.create(PASSWORD, include_vault=True)
    RestoreService().restore(service.path(receipt.backup_id), PASSWORD, tmp_path / "without-vault")
    assert not (tmp_path / "without-vault/security/vault.sqlite3").exists()
    RestoreService().restore(
        service.path(receipt.backup_id), PASSWORD, tmp_path / "with-vault", restore_vault=True
    )
    restored = Vault(tmp_path / "with-vault", "fernet")
    restored.unlock(principal, "synthetic-vault-passphrase-148726")
    assert restored.list_handles(principal)[0]["handle"] == handle
    runtime.retrieval.close()


def test_corruption_auto_enters_recovery_without_touching_data(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path)
    runtime.retrieval.close()
    (tmp_path / "runtime.sqlite3").write_bytes(b"intentionally broken primary fixture")
    before = contents(tmp_path)
    app = create_app(settings, ProbeProvider())
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/health").json()["status"] == "RECOVERY_READ_ONLY"
        assert client.post("/chat", json={"text": "/remember data = change"}).status_code == 503
        assert client.get("/memory").status_code == 503
    assert contents(tmp_path) == before
    assert RecoveryService(settings).status()["mode"] == "RECOVERY_READ_ONLY"
    with pytest.raises(BackupError, match="STORE_UNREADABLE"):
        RecoveryService(settings).records("memories")


@pytest.mark.parametrize("table", ["actions", "tasks"])
def test_invalid_journal_record_enters_recovery_before_initialization(tmp_path, table):
    settings, runtime, _, _ = seeded(tmp_path)
    runtime.retrieval.close()
    with closing(sqlite3.connect(tmp_path / f"{table}.sqlite3")) as db, db:
        db.execute(f"INSERT INTO {table}(id,record) VALUES (?, ?)", ("synthetic-invalid", "{}"))
    before = contents(tmp_path)
    assert inspect(settings)["issues"] == ["STORAGE.RECORD_INVALID"]
    with TestClient(create_app(settings, ProbeProvider()), base_url="http://localhost") as client:
        assert client.get("/health").json()["status"] == "RECOVERY_READ_ONLY"
        assert client.post("/chat", json={"text": "change"}).status_code == 503
    assert contents(tmp_path) == before


def test_schema_drift_and_explicit_recovery_do_not_migrate_or_load_model(
    tmp_path, monkeypatch, capsys
):
    settings, runtime, _, _ = seeded(tmp_path)
    with runtime.store.connect() as db:
        db.execute("UPDATE schema_migrations SET checksum='drift' WHERE version=6")
    before = contents(tmp_path)
    monkeypatch.setattr("sys.argv", ["maintenance", "--data-dir", str(tmp_path), "recovery"])
    monkeypatch.setattr(
        "adam.resilience.cli.getpass.getpass",
        lambda *args: pytest.fail("recovery must not prompt or write auth"),
    )
    main()
    assert json.loads(capsys.readouterr().out)["session_mode"] == "RECOVERY_READ_ONLY"
    assert contents(tmp_path) == before
    with pytest.raises(BackupError, match="READ_ONLY"):
        rebuild_indexes(settings)
    runtime.retrieval.close()


def test_derived_index_repair_quarantines_old_files_and_refuses_busy_index(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path)
    runtime.retrieval.close()
    vectors = tmp_path / "knowledge/vectors"
    vectors.mkdir(parents=True)
    broken = vectors / "meta.json"
    broken.write_text("broken derived metadata")
    with portalocker.Lock(str(vectors / ".lock"), mode="a+b", timeout=0):
        with pytest.raises(BackupError, match="INDEX_BUSY"):
            rebuild_indexes(settings)
    assert broken.read_text() == "broken derived metadata"
    result = rebuild_indexes(settings)
    assert result["canonical_sources_retained"] and result["quarantined_previous_index"]
    assert list((tmp_path / "knowledge").glob("vectors-quarantine-*/meta.json"))


def test_restore_api_is_isolated_and_recovery_wal_is_visible(tmp_path):
    app = create_app(load_settings(env={"ADAM_DATA_DIR": str(tmp_path)}), ProbeProvider())
    app.state.auth.initialize(OWNER)
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"password": OWNER})
        client.post("/auth/elevate", json={"password": OWNER})
        receipt = client.post("/maintenance/backups", json={"password": PASSWORD}).json()
        result = client.post(
            f"/maintenance/backups/{receipt['backup_id']}/restore", json={"password": PASSWORD}
        ).json()
        assert result["status"] == "VERIFIED" and result["target"].startswith(
            str(tmp_path / "restores")
        )
        assert client.get("/maintenance/integrity").json()["mode"] == "HEALTHY"
    settings = load_settings(env={"ADAM_DATA_DIR": str(tmp_path)})
    with closing(sqlite3.connect(tmp_path / "runtime.sqlite3")) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("UPDATE runtime_metadata SET value=value")
        db.commit()
        (tmp_path / "runtime.sqlite3-wal").write_bytes(b"synthetic unresolved WAL")
        assert "STORAGE.WAL_INVALID" in inspect(settings)["issues"]


@pytest.mark.parametrize("fault", ["settings", "identity", "journal", "memory_record"])
def test_faulted_settings_identity_journal_and_records_enter_safe_recovery(
    tmp_path, fault, monkeypatch
):
    settings, runtime, _, _ = seeded(tmp_path)
    runtime.retrieval.close()
    if fault == "settings":
        (tmp_path / "config").mkdir()
        (tmp_path / "config/restored-settings.json").write_text("invalid settings")
        monkeypatch.setenv("ADAM_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("ADAM_CONFIG", raising=False)
    elif fault == "identity":
        settings.identity_dir = tmp_path / "broken-identity"
        settings.identity_dir.mkdir()
        (settings.identity_dir / "identity.yaml").write_text("[malformed: yaml")
    elif fault == "journal":
        (tmp_path / "actions.sqlite3").write_bytes(b"invalid journal")
    else:
        with runtime.store.connect() as db:
            db.execute("UPDATE memories SET record='{}'")
    before = contents(tmp_path)
    app = create_app(None if fault == "settings" else settings, ProbeProvider())
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/health").json()["status"] == "RECOVERY_READ_ONLY"
        assert client.post("/auth/login", json={"password": OWNER}).status_code == 503
    assert contents(tmp_path) == before
