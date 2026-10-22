from dataclasses import replace
from pathlib import Path

import pytest
from adam.security.policy import Principal
from adam.tools.contracts import ToolCall
from adam.tools.registry import ToolError
from adam.tools.service import ActionService

OWNER = Principal(elevated=True)


def run(service: ActionService, call: ToolCall):
    action = service.preview(call, OWNER)
    service.approve(action.action_id, action.digest, OWNER)
    return service.execute(action.action_id, OWNER)


def test_approval_scope_and_guests(tmp_path: Path) -> None:
    service = ActionService(tmp_path)
    call = ToolCall(name="notes.create", arguments={"path": "hello.txt", "text": "hello"})
    with pytest.raises(ToolError, match="OWNER_REQUIRED"):
        service.preview(call, replace(OWNER, mode="guest"))
    with pytest.raises(ToolError, match="SCOPE_DENIED"):
        service.preview(
            call.model_copy(update={"arguments": {"path": "../escape", "text": "hi"}}), OWNER
        )
    action = service.preview(call, OWNER)
    assert not (service.scope.root / "hello.txt").exists()
    with pytest.raises(ToolError, match="APPROVAL_REQUIRED"):
        service.execute(action.action_id, OWNER)
    with pytest.raises(ToolError, match="REAUTHENTICATION_REQUIRED"):
        service.approve(action.action_id, action.digest, Principal())
    with pytest.raises(ToolError, match="APPROVAL_MISMATCH"):
        service.approve(action.action_id, "wrong", OWNER)
    service.approve(action.action_id, action.digest, OWNER, allow=False)
    with pytest.raises(ToolError, match="APPROVAL_REQUIRED"):
        service.execute(action.action_id, OWNER)


def test_create_move_undo_and_restart(tmp_path: Path) -> None:
    service = ActionService(tmp_path)
    created = run(
        service, ToolCall(name="notes.create", arguments={"path": "a.txt", "text": "hello"})
    )
    assert created.result.status == "VERIFIED"
    moved = run(
        service, ToolCall(name="files.move", arguments={"source": "a.txt", "destination": "b.txt"})
    )
    service = ActionService(tmp_path)
    assert service.execute(moved.action_id, OWNER).result.status == "VERIFIED"
    undo = service.undo(moved.action_id, OWNER)
    assert (service.scope.root / "b.txt").exists()
    service.approve(undo.action_id, undo.digest, OWNER)
    assert service.execute(undo.action_id, OWNER).result.status == "VERIFIED"
    assert service.get(moved.action_id).result.status == "UNDONE"
    assert (service.scope.root / "a.txt").read_text() == "hello"
    undone_note = service.undo(created.action_id, OWNER)
    service.approve(undone_note.action_id, undone_note.digest, OWNER)
    assert service.execute(undone_note.action_id, OWNER).result.status == "VERIFIED"
    assert not (service.scope.root / "a.txt").exists()


def test_stale_approval_conflict_and_uncertain_recovery(tmp_path: Path) -> None:
    service = ActionService(tmp_path)
    call = ToolCall(name="notes.create", arguments={"path": "a.txt", "text": "hello"})
    action = service.preview(call, OWNER)
    service.approve(action.action_id, action.digest, OWNER)
    (service.scope.root / "a.txt").write_text("someone else")
    assert service.execute(action.action_id, OWNER).result.error_code == "TOOL.STALE_PREVIEW"
    assert (service.scope.root / "a.txt").read_text() == "someone else"
    with pytest.raises(ToolError, match="IDEMPOTENCY_CONFLICT"):
        service.preview(
            call.model_copy(update={"name": "files.read", "arguments": {"path": "a.txt"}}), OWNER
        )
    action.result.status = "RUNNING"
    service.save(action)
    assert ActionService(tmp_path).execute(action.action_id, OWNER).result.status == "UNCERTAIN"
    assert (service.scope.root / "a.txt").read_text() == "someone else"


@pytest.mark.parametrize("path", ["CON.txt", "a:b", ".adam-quarantine/x", "bad.", "../x"])
def test_windows_path_edge_cases(tmp_path: Path, path: str) -> None:
    with pytest.raises(ToolError, match="SCOPE_DENIED"):
        ActionService(tmp_path).scope.path(path)


def test_directory_undo_snapshot_and_changed_note(tmp_path: Path) -> None:
    service = ActionService(tmp_path)
    directory = run(service, ToolCall(name="directories.create", arguments={"path": "empty"}))
    undo = service.undo(directory.action_id, OWNER)
    service.approve(undo.action_id, undo.digest, OWNER)
    assert service.execute(undo.action_id, OWNER).result.status == "VERIFIED"
    note = run(
        service, ToolCall(name="notes.create", arguments={"path": "note.txt", "text": "original"})
    )
    quarantined = run(service, ToolCall(name="files.quarantine", arguments={"path": "note.txt"}))
    assert quarantined.snapshot is not None
    assert service.scope.path(quarantined.snapshot, internal=True).read_text() == "original"
    undo = service.undo(quarantined.action_id, OWNER)
    service.approve(undo.action_id, undo.digest, OWNER)
    assert service.execute(undo.action_id, OWNER).result.status == "VERIFIED"
    (service.scope.root / "note.txt").write_text("edited")
    with pytest.raises(ToolError, match="UNDO_CONFLICT"):
        service.undo(note.action_id, OWNER)


def test_readonly_search_and_no_overwrite(tmp_path: Path) -> None:
    service = ActionService(tmp_path)
    run(service, ToolCall(name="notes.create", arguments={"path": "a.txt", "text": "hello"}))
    action = service.preview(ToolCall(name="files.search"), Principal(mode="guest"))
    assert service.execute(action.action_id, Principal(mode="guest")).result.data == {
        "paths": ["a.txt"]
    }
    with pytest.raises(ToolError, match="DESTINATION_EXISTS"):
        service.preview(
            ToolCall(name="notes.create", arguments={"path": "a.txt", "text": "overwrite"}), OWNER
        )
