import asyncio
import csv
import io
import json
from datetime import UTC, datetime

import pytest
from adam.api.app import create_app
from adam.core.config import Settings
from adam.core.privacy import register_secret
from adam.core.runtime import ChatRequest
from adam.evals.suite import ProbeProvider
from adam.knowledge.contracts import SourceRequest
from adam.resilience.contracts import BackupError
from adam.resilience.export import ExportFilter, ExportService, render
from adam.security.policy import Principal
from adam.tasks.service import Plan, Step
from adam.tools.contracts import ToolCall
from fastapi.testclient import TestClient
from test_backup import OWNER, seeded
from test_restore import contents


def test_all_formats_preserve_memory_provenance_history_and_epistemic_status(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path / "source")
    asyncio.run(runtime.chat(ChatRequest(text="/remember semantic language = might use Rust")))
    original = runtime.memories.search("editor")[0]
    result = ExportService(settings).export(tmp_path / "export")
    assert result["status"] == "COMPLETE" and result["integrity"] == "VERIFIED"
    bundle = json.loads((tmp_path / "export/data.json").read_text(encoding="utf-8"))
    exported = next(
        row for row in bundle["records"]["memories"] if row.get("memory_id") == original.memory_id
    )
    assert exported["provenance"] == original.model_dump(mode="json")["provenance"]
    assert datetime.fromisoformat(exported["created_at"]) == original.created_at
    assert any(row["epistemic_status"] == "UNCERTAIN" for row in bundle["records"]["memories"])
    lines = [
        json.loads(line)
        for line in (tmp_path / "export/data.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert lines[0]["section"] == "export_metadata"
    assert "UNVERIFIED" in (tmp_path / "export/data.json").read_text(encoding="utf-8")
    assert "SnapshotStudio" in (tmp_path / "export/summary.md").read_text(encoding="utf-8")
    assert list(
        csv.DictReader(io.StringIO((tmp_path / "export/records.csv").read_text(encoding="utf-8")))
    )
    assert not list((tmp_path / "export").glob("*.sqlite3"))
    runtime.retrieval.close()


def test_project_person_date_conversation_task_and_type_filters_are_selective(tmp_path):
    root = tmp_path / "source"
    settings, runtime, _, _ = seeded(root)
    event = asyncio.run(runtime.chat(ChatRequest(text="/remember project Cedar = uses Rust")))
    asyncio.run(runtime.chat(ChatRequest(text="/remember project Maple = uses Python")))
    settings.knowledge.allowed_roots = [root]
    runtime.knowledge.config = settings.knowledge
    document = root / "cedar.md"
    document.write_text("Fictional Cedar source: local namespace fixture.")
    runtime.knowledge.ingest(SourceRequest(path=str(document), namespace="Cedar"))
    task = runtime.tasks.create(
        Plan(
            goal="Cedar create note",
            intent="change",
            steps=[
                Step(
                    step_id="write",
                    objective="Synthetic note",
                    call=ToolCall(
                        name="notes.create",
                        arguments={"path": "cedar.txt", "text": "synthetic project note"},
                    ),
                )
            ],
        ),
        Principal(),
    )
    runtime.tasks.approve(task.task_id, task.digest, Principal(elevated=True))
    runtime.tasks.run(task.task_id, Principal(elevated=True))
    service = ExportService(settings)
    project = service.collect(ExportFilter(project="Cedar"))
    assert (
        project["counts"]["memories"]
        == project["counts"]["knowledge"]
        == project["counts"]["tasks"]
        == project["counts"]["actions"]
        == 1
    )
    assert "Maple" not in json.dumps(project)
    assert all(
        count == 0
        for count in service.collect(ExportFilter(person="someone_else"))["counts"].values()
    )
    today = datetime.now(UTC).date().isoformat()
    dated = service.collect(ExportFilter(since=today, until=today))
    assert dated["counts"]["memories"] == 3 and dated["counts"]["actions"] == 0
    assert all(
        count == 0 for count in service.collect(ExportFilter(until="2000-01-01"))["counts"].values()
    )
    conversation = service.collect(ExportFilter(conversation_id=str(event.session_id)))
    assert set(conversation["counts"]) == {"memories", "conversations"}
    assert conversation["counts"]["memories"] == 1
    selected_task = service.collect(ExportFilter(task_id=task.task_id))
    assert (
        set(selected_task["counts"]) == {"tasks", "actions"}
        and selected_task["counts"]["tasks"] == 1
    )
    assert service.collect(ExportFilter(memory_type="preference"))["counts"] == {"memories": 1}
    runtime.retrieval.close()


def test_known_secrets_and_denied_subjects_never_appear_in_export(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path / "source")
    secret = "synthetic-known-export-secret-85279"
    register_secret(secret)
    with runtime.store.connect() as db:
        row = db.execute("SELECT memory_id,record FROM memories").fetchone()
        raw = json.loads(row[1])
        raw["content"] = secret
        db.execute("UPDATE memories SET record=? WHERE memory_id=?", (json.dumps(raw), row[0]))
        db.execute("UPDATE turns SET user_text=?", (secret,))
    result = ExportService(settings).export(tmp_path / "redacted")
    assert result["omitted"]["credential_or_policy"] == 1
    assert all(
        secret.encode() not in file.read_bytes() for file in (tmp_path / "redacted").iterdir()
    )
    assert result["counts"]["memories"] == 0
    with runtime.store.connect() as db:
        raw["content"] = "synthetic private other-person statement"
        raw["subjects"] = ["another_person"]
        db.execute("UPDATE memories SET record=? WHERE memory_id=?", (json.dumps(raw), row[0]))
    assert ExportService(settings).collect(ExportFilter())["counts"]["memories"] == 0
    runtime.retrieval.close()


def test_candidate_export_preserves_unconfirmed_status_and_evidence(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path / "source")
    asyncio.run(runtime.chat(ChatRequest(text="I prefer maybe using a dark theme")))
    with runtime.store.connect() as db:
        assert runtime.consolidation.scan_candidates(db) == 1
    candidate = runtime.consolidation.candidates()[0]
    bundle = ExportService(settings).collect(ExportFilter(memory_type="preference"))
    exported = next(
        row for row in bundle["records"]["memories"] if row["record_type"] == "candidate"
    )
    assert exported["status"] == "CANDIDATE" and exported["epistemic_status"] == "UNCERTAIN"
    assert exported["evidence"] == candidate.evidence.model_dump(mode="json")
    assert runtime.consolidation.candidates()[0].status == "CANDIDATE"
    runtime.retrieval.close()


def test_recovery_export_is_read_only_and_marks_unreadable_sections_partial(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path / "source")
    runtime.retrieval.close()
    (settings.data_dir / "tasks.sqlite3").write_bytes(b"faulted task store")
    before = contents(settings.data_dir)
    with pytest.raises(BackupError, match="READ_ONLY"):
        ExportService(settings).export(tmp_path / "normal")
    result = ExportService(settings).export(tmp_path / "salvage", recovery=True)
    assert result["status"] == "PARTIAL" and result["section_status"]["tasks"] == "UNREADABLE"
    assert result["counts"]["memories"] == 1
    assert contents(settings.data_dir) == before
    assert not (tmp_path / "normal").exists()


def test_export_failure_existing_target_record_limit_and_csv_formulas(tmp_path, monkeypatch):
    settings, runtime, _, _ = seeded(tmp_path / "source")
    service = ExportService(settings)
    with pytest.raises(BackupError, match="RECORD_LIMIT"):
        service.export(tmp_path / "limited", ExportFilter(max_records=1))
    assert not (tmp_path / "limited").exists()
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(BackupError, match="FRESH_TARGET_REQUIRED"):
        service.export(existing)
    from pathlib import Path

    monkeypatch.setattr(Path, "rename", lambda *args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(BackupError, match="IO_FAILED"):
        service.export(tmp_path / "failed")
    assert not (tmp_path / "failed").exists() and not list(tmp_path.glob(".adam-export-*"))
    bundle = {"records": {"memories": [{"memory_id": "  =1+1", "created_at": "2026-10-06"}]}}
    rendered = render(bundle, ["csv"])
    row = next(csv.DictReader(io.StringIO(rendered["records.csv"].decode())))
    assert row["record_id"].startswith("'")
    runtime.retrieval.close()


@pytest.mark.parametrize(
    "fields",
    [
        {"since": "2030-01-01", "until": "2020-01-01"},
        {"project": ""},
        {"conversation_id": "../../outside"},
        {"memory_type": "unsupported"},
        {"task_id": "a" * 36, "conversation_id": "b" * 36},
    ],
)
def test_invalid_export_filters_are_rejected(fields):
    with pytest.raises(ValueError):
        ExportFilter.model_validate(fields)


def test_export_api_preserves_fresh_owner_boundary_and_fixed_download_names(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), ProbeProvider())
    app.state.auth.initialize(OWNER)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.post("/maintenance/exports", json={}).status_code == 401
        client.post("/auth/login", json={"password": OWNER})
        assert client.post("/maintenance/exports", json={}).status_code == 403
        client.post("/auth/elevate", json={"password": OWNER})
        client.post("/chat", json={"text": "/remember preference test = synthetic value"})
        result = client.post("/maintenance/exports", json={"memory_type": "preference"}).json()
        assert result["integrity"] == "VERIFIED"
        identifier = result["export_id"]
        download = client.get(f"/maintenance/exports/{identifier}/data.json")
        assert download.status_code == 200 and "synthetic value" in download.text
        assert client.get(f"/maintenance/exports/{identifier}/auth.sqlite3").status_code == 409
        client.post("/auth/switch", json={"mode": "guest"})
        assert client.get(f"/maintenance/exports/{identifier}/data.json").status_code == 403
