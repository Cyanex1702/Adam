import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from adam.compute.catalog import Catalog, ModelProfile, publish
from adam.core.config import Settings, load_settings
from adam.core.migrations import MIGRATIONS, migrate
from adam.desktop.service import desktop_app
from adam.resilience.recovery import inspect
from fastapi.testclient import TestClient


@pytest.mark.parametrize("version", range(1, 8))
def test_every_real_legacy_schema_is_readable_and_upgrades_without_reset(tmp_path, version):
    from adam.security.auth import AuthManager

    path = tmp_path / "runtime.sqlite3"
    migrate(path, MIGRATIONS[:version])
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO runtime_metadata VALUES ('legacy-upgrade-test','preserved')")
        if version >= 2:
            db.execute(
                "INSERT INTO sessions(session_id,created_at,updated_at) VALUES (?,?,?)",
                ("legacy-session", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            )
            db.execute(
                "INSERT INTO turns(session_id,user_text,assistant_text,"
                "created_at,trace_id,model_id) VALUES (?,?,?,?,?,?)",
                (
                    "legacy-session",
                    "synthetic question",
                    "synthetic answer",
                    "2026-01-01",
                    "old-trace",
                    "test",
                ),
            )
    owner = "synthetic-legacy-owner-password"
    AuthManager(tmp_path).initialize(owner)
    auth_path = tmp_path / "security/auth.sqlite3"
    before = (path.read_bytes(), auth_path.read_bytes())
    settings = Settings(data_dir=tmp_path)
    result = inspect(settings)
    assert result["mode"] == "HEALTHY"
    assert result["schemas"]["runtime.sqlite3"] == version
    assert before == (path.read_bytes(), auth_path.read_bytes())  # inspection never migrates
    boundary = desktop_app(settings, "legacy-test-capability", probe=True)
    with TestClient(
        boundary, base_url="http://localhost", headers={"x-adam-desktop": "legacy-test-capability"}
    ) as client:
        assert client.get("/desktop/status").json()["recovery"] is False
        assert client.get("/desktop/status").json()["configured"] is True
        assert client.post("/auth/login", json={"password": owner}).status_code == 200
        report = client.get("/desktop/diagnostics").json()
        assert report["storage"]["schemas"]["runtime.sqlite3"] == 7
        assert "synthetic question" not in json.dumps(report)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 7
        assert (
            db.execute(
                "SELECT value FROM runtime_metadata WHERE key='legacy-upgrade-test'"
            ).fetchone()[0]
            == "preserved"
        )
        if version >= 2:
            assert db.execute("SELECT user_text,assistant_text FROM turns").fetchall() == [
                ("synthetic question", "synthetic answer")
            ]


def test_schema_damage_is_identified_without_migrating_or_resetting(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    migrate(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DROP TABLE knowledge_chunks")
    before = path.read_bytes()
    result = inspect(Settings(data_dir=tmp_path))
    assert result["mode"] == "RECOVERY_READ_ONLY"
    assert result["stores"]["runtime.sqlite3"] == "STORAGE.SCHEMA_MISMATCH"
    assert path.read_bytes() == before


def test_legacy_catalog_same_model_retains_saved_generation_settings(tmp_path):
    portable = load_settings(env={"ADAM_DATA_DIR": str(tmp_path)})
    portable.model.context_limit = 2048
    portable.model.max_tokens = 384
    publish(
        tmp_path,
        "config/model-catalog.json",
        Catalog(profiles={"current": ModelProfile(profile_id="current", model=portable.model)}),
    )
    desktop = load_settings(env={"ADAM_DATA_DIR": str(tmp_path)})
    assert desktop.model.context_limit == 2048
    assert desktop.model.max_tokens == 384
    assert inspect(desktop)["mode"] == "HEALTHY"


def test_valid_committed_wal_is_not_a_recovery_condition(tmp_path):
    settings = Settings(data_dir=tmp_path)
    path = tmp_path / "runtime.sqlite3"
    migrate(path)
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT OR REPLACE INTO runtime_metadata VALUES ('repair-test','kept')")
        writer.commit()
        wal = path.with_name(path.name + "-wal")
        assert wal.stat().st_size > 32
        before = (path.read_bytes(), wal.read_bytes())
        assert inspect(settings)["mode"] == "HEALTHY"
        assert before == (path.read_bytes(), wal.read_bytes())
        assert writer.execute(
            "SELECT value FROM runtime_metadata WHERE key='repair-test'"
        ).fetchone() == ("kept",)


def test_recovery_desktop_status_exposes_safe_issue_codes(tmp_path):
    (tmp_path / "runtime.sqlite3").write_bytes(b"not a database")
    boundary = desktop_app(Settings(data_dir=tmp_path), "synthetic-repair-capability", probe=True)
    with TestClient(boundary, headers={"x-adam-desktop": "synthetic-repair-capability"}) as client:
        status = client.get("/desktop/status").json()
        assert status["recovery"] is True
        assert "STORAGE.INTEGRITY_FAILED" in status["issues"]
        assert "not a database" not in json.dumps(status)


def test_abrupt_writer_exit_retains_committed_wal_and_history(tmp_path):
    settings = Settings(data_dir=tmp_path)
    path = tmp_path / "runtime.sqlite3"
    migrate(path)
    script = """import sqlite3,sys,os
db=sqlite3.connect(sys.argv[1])
db.execute('PRAGMA journal_mode=WAL')
db.execute('PRAGMA wal_autocheckpoint=0')
db.execute("INSERT OR REPLACE INTO runtime_metadata VALUES ('crash-fixture','committed')")
db.commit()
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", script, str(path)], check=True, timeout=20)
    wal = path.with_name(path.name + "-wal")
    before = (path.read_bytes(), wal.read_bytes())
    assert inspect(settings)["mode"] == "HEALTHY"
    assert before == (path.read_bytes(), wal.read_bytes())
    from adam.resilience.recovery import recovery_readonly

    with closing(recovery_readonly(path)) as db:
        assert db.execute(
            "SELECT value FROM runtime_metadata WHERE key='crash-fixture'"
        ).fetchone() == ("committed",)


def test_windows_profile_mapping_requires_unanimous_private_anchors(tmp_path, monkeypatch):
    if os.name != "nt":
        return
    from adam.core.config import canonical_profile_dir

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    root = tmp_path / "ADAM"
    cache = tmp_path / "Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/ADAM"
    root.mkdir()
    cache.mkdir(parents=True)
    (root / "runtime.sqlite3").write_bytes(b"virtual-file-fixture")
    (cache / "runtime.sqlite3").write_bytes(b"virtual-file-fixture")
    original = Path.resolve

    def virtual_resolve(path, *args, **kwargs):
        if path == root / "runtime.sqlite3":
            return original(cache / "runtime.sqlite3", *args, **kwargs)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", virtual_resolve)
    assert canonical_profile_dir(root) == cache
    (root / "security").mkdir()
    (root / "security/auth.sqlite3").write_bytes(b"separate-host-credential-fixture")
    assert canonical_profile_dir(root) == root  # never merge private profiles


def test_invalid_performance_preference_remains_recoverable_and_unchanged(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    path = config / "performance.json"
    path.write_text('{"mode":"disable-all-guards"}')
    assert "CONFIG.PERFORMANCE_INVALID" in inspect(Settings(data_dir=tmp_path))["issues"]
    assert path.read_text() == '{"mode":"disable-all-guards"}'


def test_slow_model_startup_does_not_block_login_or_diagnostic_checks(tmp_path, monkeypatch):
    import asyncio
    import time

    from adam.compute.migration import ModelController

    stopped = []

    async def slow_start(controller):
        controller.manager.state = "LOADING"
        controller.manager.detached = True
        try:
            await asyncio.sleep(30)
        finally:
            stopped.append(True)

    monkeypatch.setattr(ModelController, "startup", slow_start)
    boundary = desktop_app(Settings(data_dir=tmp_path), "synthetic-startup-capability", probe=True)
    boundary.ready.state.auth.initialize("synthetic-existing-owner-password")
    started = time.monotonic()
    with TestClient(
        boundary,
        base_url="http://localhost",
        headers={"x-adam-desktop": "synthetic-startup-capability"},
    ) as client:
        assert client.get("/desktop/status").json()["configured"] is True
        assert client.get("/desktop/diagnostics").status_code == 200
        assert (
            client.post(
                "/auth/login", json={"password": "synthetic-existing-owner-password"}
            ).status_code
            == 200
        )
        assert time.monotonic() - started < 5
    assert stopped == [True]
