import sqlite3
from pathlib import Path

import pytest
from adam.core.config import load_settings, resolve_data_dir
from adam.core.contracts import ErrorEnvelope, EventEnvelope, TraceId, new_id
from adam.core.migrations import MIGRATIONS, migrate
from pydantic import ValidationError


def test_config_precedence(tmp_path: Path) -> None:
    config = tmp_path / "user.toml"
    config.write_text('[model]\nmodel_id="other"\nmax_tokens=77\n', encoding="utf-8")
    settings = load_settings(config, {"ADAM_MODEL_ID": "override", "ADAM_DATA_DIR": str(tmp_path)})
    assert settings.model.model_id == "override"
    assert settings.model.max_tokens == 77
    assert settings.data_dir == tmp_path.resolve()
    assert load_settings(env={}).model.model_id == "qwen3-8b"


def test_data_path(tmp_path: Path) -> None:
    assert resolve_data_dir({"ADAM_DATA_DIR": str(tmp_path)}) == tmp_path.resolve()


def test_envelopes_round_trip() -> None:
    trace = TraceId(new_id())
    event = EventEnvelope(event_type="system.started", trace_id=trace)
    assert EventEnvelope.model_validate_json(event.model_dump_json()) == event
    error = ErrorEnvelope(code="MODEL.UNAVAILABLE", message="Unavailable", trace_id=trace)
    assert ErrorEnvelope.model_validate_json(error.model_dump_json()) == error


@pytest.mark.parametrize("url", ["https://example.com", "http://user:secret@localhost:8080"])
def test_remote_and_secret_model_urls_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        load_settings(env={"ADAM_MODEL_URL": url})


def test_unimplemented_flag_rejected(tmp_path: Path) -> None:
    config = tmp_path / "bad.toml"
    config.write_text("[features]\nvision=true\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(config, {})


def test_migration_idempotent_and_transactional(tmp_path: Path) -> None:
    database = tmp_path / "runtime.sqlite3"
    assert migrate(database, MIGRATIONS[:1]) == migrate(database, MIGRATIONS[:1]) == 1
    with pytest.raises(sqlite3.OperationalError):
        migrate(
            database,
            (
                (1, ("CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",)),
                (2, ("CREATE TABLE rollback_test (id INTEGER)", "INVALID SQL")),
            ),
        )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
        assert not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='rollback_test'"
        ).fetchall()
    assert migrate(database) == migrate(database) == 7
