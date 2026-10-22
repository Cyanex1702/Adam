from pathlib import Path

import pytest
from adam.security.policy import Principal
from adam.tasks.service import Plan, Step, TaskService
from adam.tools.contracts import ToolCall
from adam.tools.registry import ToolError
from adam.tools.service import ActionService

OWNER = Principal(elevated=True)


def services(tmp_path: Path):
    actions = ActionService(tmp_path)
    return actions, TaskService(tmp_path, actions)


def note_step():
    return Step(
        step_id="write",
        objective="Create note",
        call=ToolCall(
            name="notes.create", arguments={"path": "note.txt", "text": "verified content"}
        ),
    )


def test_plan_execute_verify_restart(tmp_path: Path) -> None:
    actions, tasks = services(tmp_path)
    plan = Plan(
        goal="Create and check note",
        intent="fix_and_test",
        steps=[
            note_step(),
            Step(
                step_id="test",
                objective="Verify content",
                dependencies=["write"],
                call=ToolCall(name="files.read", arguments={"path": "note.txt"}),
                expected_text="verified content",
            ),
        ],
    )
    task = tasks.create(plan, OWNER)
    assert not (actions.scope.root / "note.txt").exists()
    tasks.approve(task.task_id, task.digest, OWNER)
    result = tasks.run(task.task_id, OWNER)
    assert result.status == "COMPLETED"
    assert all(step.status == "COMPLETED" for step in result.plan.steps)
    _, restarted = services(tmp_path)
    assert restarted.run(task.task_id, OWNER).status == "COMPLETED"
    assert len(actions.list()) == 2


def test_invalid_graph_observe_and_missing_test(tmp_path: Path) -> None:
    _, tasks = services(tmp_path)
    with pytest.raises(ToolError, match="OBSERVE_CANNOT_MODIFY"):
        tasks.create(Plan(goal="diagnose only", steps=[note_step()]), OWNER)
    with pytest.raises(ToolError, match="TEST_REQUIRED"):
        tasks.create(Plan(goal="fix and test", intent="fix_and_test", steps=[note_step()]), OWNER)
    step = note_step()
    step.dependencies = ["missing"]
    with pytest.raises(ToolError, match="INVALID_DEPENDENCIES"):
        tasks.create(Plan(goal="bad graph", intent="change", steps=[step]), OWNER)
    with pytest.raises(ToolError, match="CLARIFICATION_REQUIRED"):
        tasks.planner.from_goal("clean everything")


def test_failure_retry_cancel_and_replan(tmp_path: Path) -> None:
    _, tasks = services(tmp_path)
    plan = Plan(
        goal="Read missing file",
        steps=[
            Step(
                step_id="read",
                objective="read",
                call=ToolCall(name="files.read", arguments={"path": "missing.txt"}),
            )
        ],
        retry_limit=2,
    )
    task = tasks.create(plan, OWNER)
    tasks.approve(task.task_id, task.digest, OWNER)
    result = tasks.run(task.task_id, OWNER)
    assert result.status == "FAILED"
    assert result.plan.steps[0].attempts == 3
    replacement = tasks.replan(
        task.task_id,
        Plan(
            goal="inspect system",
            steps=[Step(step_id="info", objective="inspect", call=ToolCall(name="system.info"))],
        ),
        OWNER,
    )
    assert replacement.approved_until == 0
    tasks.cancel(replacement.task_id, OWNER)
    assert tasks.run(replacement.task_id, OWNER).status == "CANCELLED"


def test_organize_dry_run_and_verification_failure(tmp_path: Path) -> None:
    actions, tasks = services(tmp_path)
    (actions.scope.root / "a.txt").write_text("alpha")
    plan = tasks.planner.from_goal("organize .")
    task = tasks.create(plan, OWNER)
    assert (actions.scope.root / "a.txt").exists()
    tasks.approve(task.task_id, task.digest, OWNER)
    assert tasks.run(task.task_id, OWNER).status == "COMPLETED"
    assert (actions.scope.root / "txt" / "a.txt").read_text() == "alpha"
    failing = tasks.create(
        Plan(
            goal="check content",
            steps=[
                Step(
                    step_id="check",
                    objective="check",
                    call=ToolCall(name="files.read", arguments={"path": "txt/a.txt"}),
                    expected_text="absent",
                )
            ],
        ),
        OWNER,
    )
    tasks.approve(failing.task_id, failing.digest, OWNER)
    assert tasks.run(failing.task_id, OWNER).status == "FAILED"


def test_stale_plan_denied(tmp_path: Path) -> None:
    actions, tasks = services(tmp_path)
    task = tasks.create(Plan(goal="note", intent="change", steps=[note_step()]), OWNER)
    tasks.approve(task.task_id, task.digest, OWNER)
    (actions.scope.root / "note.txt").write_text("concurrent writer")
    with pytest.raises(ToolError, match="STALE_PLAN"):
        tasks.run(task.task_id, OWNER)
