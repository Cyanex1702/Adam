import sqlite3

import pytest
from adam.security.policy import Principal
from adam.tasks.service import Plan, Step, TaskService
from adam.tools.contracts import ToolCall
from adam.tools.registry import ToolError
from adam.tools.service import ActionService

OWNER = Principal(elevated=True)


def create(tmp_path, steps):
    actions = ActionService(tmp_path)
    tasks = TaskService(tmp_path, actions)
    task = tasks.create(Plan(goal="synthetic recovery test", intent="change", steps=steps), OWNER)
    tasks.approve(task.task_id, task.digest, OWNER)
    return actions, tasks, task


def note(identifier, path):
    return Step(
        step_id=identifier,
        objective="Create synthetic note",
        call=ToolCall(name="notes.create", arguments={"path": path, "text": "synthetic content"}),
    )


def test_crash_after_verified_effect_never_duplicates(tmp_path, monkeypatch):
    actions, tasks, task = create(tmp_path, [note("one", "one.txt")])
    save = tasks.save

    def crash(record):
        if record.plan.steps[0].status == "COMPLETED":
            raise RuntimeError("synthetic crash before step checkpoint")
        save(record)

    monkeypatch.setattr(tasks, "save", crash)
    with pytest.raises(RuntimeError):
        tasks.run(task.task_id, OWNER)
    restarted = TaskService(tmp_path, ActionService(tmp_path))
    assert restarted.run(task.task_id, OWNER).status == "COMPLETED"
    assert len(actions.list()) == 1
    assert (actions.scope.root / "one.txt").read_text() == "synthetic content"


def test_cancel_during_step_is_durable(tmp_path, monkeypatch):
    actions, tasks, task = create(tmp_path, [note("one", "one.txt"), note("two", "two.txt")])
    perform = actions.perform

    def cancel_during_action(action, paths):
        data = perform(action, paths)
        tasks.cancel(task.task_id, OWNER)
        return data

    monkeypatch.setattr(actions, "perform", cancel_during_action)
    assert tasks.run(task.task_id, OWNER).status == "CANCELLED"
    assert tasks.get(task.task_id).status == "CANCELLED"
    assert (actions.scope.root / "one.txt").exists()
    assert not (actions.scope.root / "two.txt").exists()


def test_resource_conflict_waits_without_duplicate_effect(tmp_path):
    actions, tasks, task = create(tmp_path, [note("one", "one.txt")])
    with sqlite3.connect(actions.lock_path) as locked:
        locked.execute("BEGIN IMMEDIATE")
        assert tasks.run(task.task_id, OWNER).status == "WAITING_FOR_RESOURCE"
        assert not (actions.scope.root / "one.txt").exists()
    assert tasks.run(task.task_id, OWNER).status == "COMPLETED"
    assert len(actions.list()) == 1


def test_expired_task_and_bounded_replanning(tmp_path):
    _, tasks, task = create(tmp_path, [note("one", "one.txt")])
    task.approved_until = 0
    tasks.save(task)
    with pytest.raises(ToolError, match="APPROVAL_REQUIRED"):
        tasks.run(task.task_id, OWNER)
    failing = Plan(
        goal="Missing file",
        steps=[
            Step(
                step_id="read",
                objective="Read",
                call=ToolCall(name="files.read", arguments={"path": "missing.txt"}),
            )
        ],
    )
    record = tasks.create(failing, OWNER)
    for index in range(3):
        tasks.approve(record.task_id, record.digest, OWNER)
        assert tasks.run(record.task_id, OWNER).status == "FAILED"
        if index < 2:
            record = tasks.replan(record.task_id, failing, OWNER)
    with pytest.raises(ToolError, match="REPLAN_LIMIT"):
        tasks.replan(record.task_id, failing, OWNER)


def test_authority_rechecked_between_steps(tmp_path):
    from dataclasses import replace

    actions, tasks, task = create(tmp_path, [note("one", "one.txt"), note("two", "two.txt")])
    calls = 0

    def authorize():
        nonlocal calls
        calls += 1
        return OWNER if calls == 1 else replace(OWNER, elevated=False)

    with pytest.raises(ToolError, match="REAUTHENTICATION_REQUIRED"):
        tasks.run(task.task_id, OWNER, authorize)
    assert (actions.scope.root / "one.txt").exists()
    assert not (actions.scope.root / "two.txt").exists()


def test_sqlite_handles_close_after_receipt_operations(tmp_path):
    actions, tasks, task = create(tmp_path, [note("one", "one.txt")])
    tasks.run(task.task_id, OWNER)
    for path in [actions.path, actions.lock_path, tasks.path, tasks.lock_path]:
        relocated = path.with_suffix(".closed")
        path.rename(relocated)
        relocated.rename(path)


def test_uncertain_task_cannot_be_replayed_or_replanned(tmp_path):
    _, tasks, task = create(tmp_path, [note("one", "one.txt")])
    task.status = "PAUSED"
    task.plan.steps[0].status = "UNCERTAIN"
    tasks.save(task)
    with pytest.raises(ToolError, match="RECOVERY_REVIEW_REQUIRED"):
        tasks.run(task.task_id, OWNER)
    assert tasks.get(task.task_id).plan.steps[0].status == "UNCERTAIN"
    with pytest.raises(ToolError, match="RECOVERY_REVIEW_REQUIRED"):
        tasks.replan(task.task_id, task.plan, OWNER)
