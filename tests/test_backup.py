import asyncio
import io
import sqlite3
import zipfile
from contextlib import closing

import pytest
from adam.api.app import create_app
from adam.core.config import Settings
from adam.core.runtime import ChatRequest, Runtime
from adam.evals.suite import ProbeProvider
from adam.resilience.archive import BackupService, decode, digest, encode
from adam.resilience.contracts import BackupError
from adam.security.auth import AuthManager
from adam.security.policy import Principal
from adam.security.vault import Vault
from fastapi.testclient import TestClient

PASSWORD = "synthetic-backup-passphrase-32671"
OWNER = "synthetic-owner-passphrase-87213"


def seeded(root):
    settings = Settings(data_dir=root)
    runtime = Runtime(settings, ProbeProvider())
    asyncio.run(runtime.chat(ChatRequest(text="/remember preference editor = SnapshotStudio")))
    auth = AuthManager(root)
    auth.initialize(OWNER)
    token = auth.issue("owner", OWNER)
    return settings, runtime, auth, token


def test_encrypted_snapshot_is_consistent_and_excludes_tokens_vault_models_indexes(tmp_path):
    settings, runtime, auth, token = seeded(tmp_path)
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "fake.gguf").write_bytes(b"not model data")
    (tmp_path / "knowledge" / "vectors").mkdir(parents=True)
    (tmp_path / "knowledge" / "vectors" / "corrupt.db").write_bytes(b"derived corruption")
    service = BackupService(settings)
    receipt = service.create(PASSWORD)
    archive = service.path(receipt.backup_id)
    assert b"SnapshotStudio" not in archive.read_bytes()
    manifest, files = service.read(archive, PASSWORD)
    assert not manifest.vault_included and "security/vault.sqlite3" not in files
    assert not any(name.startswith(("models/", "knowledge/vectors/", "audit/")) for name in files)
    assert manifest.identity_digest == runtime.identity.digest
    with closing(sqlite3.connect(":memory:")) as db:
        db.deserialize(files["runtime.sqlite3"])
        assert "SnapshotStudio" in db.execute("SELECT record FROM memories").fetchone()[0]
    with closing(sqlite3.connect(":memory:")) as db:
        db.deserialize(files["security/auth.sqlite3"])
        assert db.execute("SELECT COUNT(*) FROM tokens").fetchone()[0] == 0
    assert auth.resolve(token).mode == "owner"
    runtime.retrieval.close()


def test_wrong_password_tampering_checksum_and_identity_fail_closed(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path)
    service = BackupService(settings)
    receipt = service.create(PASSWORD)
    path = service.path(receipt.backup_id)
    with pytest.raises(BackupError, match="AUTHENTICATION_FAILED"):
        service.read(path, "different-synthetic-passphrase")
    data = bytearray(path.read_bytes())
    data[-10] ^= 1
    broken = tmp_path / "broken.adambak"
    broken.write_bytes(data)
    with pytest.raises(BackupError, match="AUTHENTICATION_FAILED"):
        service.read(broken, PASSWORD)
    manifest, files = service.read(path, PASSWORD)
    files["config/settings.json"] += b" "
    with pytest.raises(BackupError, match="CHECKSUM_FAILED"):
        decode(encode(manifest, files))
    manifest.files["config/settings.json"].size = len(files["config/settings.json"])
    manifest.files["config/settings.json"].sha256 = digest(files["config/settings.json"])
    manifest.identity_digest = "incorrect"
    with pytest.raises(BackupError, match="IDENTITY_MISMATCH"):
        decode(encode(manifest, files))
    runtime.retrieval.close()


def test_wal_snapshot_and_explicit_vault_preserve_encrypted_state(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path)
    with runtime.store.connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
    vault = Vault(tmp_path, "fernet")
    principal = Principal(elevated=True)
    vault.unlock(principal, "synthetic-vault-passphrase-76381")
    vault.put(principal, "synthetic-testing", "synthetic-private-value-61593")
    service = BackupService(settings)
    receipt = service.create(PASSWORD, include_vault=True)
    manifest, files = service.read(service.path(receipt.backup_id), PASSWORD)
    assert manifest.vault_included and "security/vault.sqlite3" in files
    assert b"synthetic-private-value-61593" not in files["security/vault.sqlite3"]
    with closing(sqlite3.connect(":memory:")) as db:
        db.deserialize(files["runtime.sqlite3"])
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    runtime.retrieval.close()


def test_archive_paths_duplicates_compression_and_links_are_rejected(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path)
    service = BackupService(settings)
    manifest, files = service.snapshot(False, "daily")
    for forbidden in ["../outside", "tool-sandbox/../outside", "tool-sandbox/CON.txt", "C:/x"]:
        stream = io.BytesIO()
        manifest.files[forbidden] = manifest.files["runtime.sqlite3"]
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("manifest.json", manifest.model_dump_json())
            for name, value in files.items():
                archive.writestr(name, value)
            archive.writestr(forbidden, files["runtime.sqlite3"])
        with pytest.raises(BackupError, match="PATH_DENIED"):
            decode(stream.getvalue())
        del manifest.files[forbidden]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest.model_dump_json())
    with pytest.raises(BackupError, match="SIZE_LIMIT"):
        decode(stream.getvalue())
    assert not (tmp_path.parent / "outside").exists()
    runtime.retrieval.close()


def test_retention_generations_and_failure_do_not_claim_success_or_prune(tmp_path, monkeypatch):
    settings, runtime, _, _ = seeded(tmp_path)
    settings.backup.daily = 1
    service = BackupService(settings)
    first = service.create(PASSWORD)
    weekly = service.create(PASSWORD, generation="weekly")
    second = service.create(PASSWORD)
    assert not service.path(first.backup_id).exists()
    assert service.path(second.backup_id).exists() and service.path(weekly.backup_id).exists()
    before = service.list()
    monkeypatch.setattr(
        "adam.resilience.archive.os.replace", lambda *args: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(BackupError, match="IO_FAILED"):
        service.create(PASSWORD)
    assert service.list() == before and not list(service.directory.glob("*.part"))
    with pytest.raises(BackupError, match="PASSPHRASE_LENGTH"):
        service.create("short")
    runtime.retrieval.close()


def test_busy_executor_and_core_corruption_are_visible(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path)
    service = BackupService(settings)
    with closing(sqlite3.connect(runtime.actions.lock_path)) as lock:
        lock.execute("BEGIN IMMEDIATE")
        with pytest.raises(BackupError, match="STORE_BUSY"):
            service.create(PASSWORD)
    runtime.retrieval.close()
    (tmp_path / "runtime.sqlite3").write_bytes(b"corrupt core")
    with pytest.raises(BackupError, match="INTEGRITY_FAILED"):
        service.create(PASSWORD)
    assert not service.list()


def test_backup_api_requires_fresh_owner_and_never_echoes_passphrase(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), ProbeProvider())
    app.state.auth.initialize(OWNER)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/maintenance/backups").status_code == 401
        client.post("/auth/login", json={"password": OWNER})
        assert client.get("/maintenance/backups").status_code == 403
        client.post("/auth/elevate", json={"password": OWNER})
        receipt = client.post("/maintenance/backups", json={"password": PASSWORD})
        assert receipt.status_code == 200 and PASSWORD not in receipt.text
        identifier = receipt.json()["backup_id"]
        verified = client.post(
            f"/maintenance/backups/{identifier}/verify", json={"password": PASSWORD}
        )
        assert verified.json()["status"] == "VERIFIED"
        assert client.get(f"/maintenance/backups/{identifier}/download").content.startswith(
            b"ADAMBK01"
        )
        invalid = client.post(
            "/maintenance/backups", json={"password": PASSWORD, "unexpected": True}
        )
        assert invalid.status_code == 422 and PASSWORD not in invalid.text
        client.post("/auth/switch", json={"mode": "guest"})
        assert client.get("/maintenance/backups").status_code == 403
