import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing, suppress
from pathlib import Path
from typing import Literal

from pydantic import Field

from adam.core.contracts import Contract, new_id
from adam.core.privacy import contains_secret
from adam.security.policy import Principal
from adam.tools.contracts import ToolCall
from adam.tools.registry import ToolError
from adam.tools.service import ActionService


class Step(Contract):
    step_id: str = Field(min_length=1, max_length=64, pattern=r"^[\w-]+$")
    objective: str = Field(min_length=1, max_length=512)
    call: ToolCall
    dependencies: list[str] = Field(default_factory=list, max_length=64)
    expected_text: str | None = Field(default=None, max_length=2048)
    status: str = "WAITING"
    attempts: int = 0
    action_id: str | None = None


class Plan(Contract):
    goal: str = Field(min_length=1, max_length=2048)
    intent: Literal["observe", "change", "fix_and_test"] = "observe"
    priority: Literal["INTERACTIVE", "BACKGROUND", "MANUAL"] = "MANUAL"
    steps: list[Step] = Field(min_length=1, max_length=64)
    retry_limit: int = Field(default=1, ge=0, le=2)
    timeout_seconds: int = Field(default=120, ge=1, le=600)


class Task(Contract):
    task_id: str
    plan: Plan
    digest: str
    status: str = "WAITING_FOR_PERMISSION"
    created_by: str
    created_at: float
    approved_until: float = 0
    replans: int = 0
    error_code: str | None = None
    before: dict[str, str] = Field(default_factory=dict)
    elapsed_seconds: float = 0


class Planner:
    def __init__(self, actions: ActionService) -> None:
        self.actions = actions

    def validate(self, plan: Plan) -> Plan:
        identifiers: set[str] = set()
        has_change = False
        for step in plan.steps:
            if step.step_id in identifiers or not set(step.dependencies) <= identifiers:
                raise ToolError("TASK.INVALID_DEPENDENCIES")
            identifiers.add(step.step_id)
            if step.status != "WAITING" or step.attempts or step.action_id:
                raise ToolError("TASK.INVALID_STEP_STATE")
            step.call = self.actions.registry.validate(step.call)
            metadata = self.actions.registry.metadata(step.call.name)
            has_change |= metadata.risk_level >= 2
            self.actions.paths(step.call)
        if has_change and plan.intent == "observe":
            raise ToolError("TASK.OBSERVE_CANNOT_MODIFY")
        if plan.intent == "fix_and_test" and (
            plan.steps[-1].expected_text is None
            or self.actions.registry.metadata(plan.steps[-1].call.name).risk_level >= 2
            or not plan.steps[-1].dependencies
        ):
            raise ToolError("TASK.TEST_REQUIRED")
        if contains_secret(plan.model_dump_json()):
            raise ToolError("TASK.SECRET_INPUT_DENIED")
        return plan

    def from_goal(self, goal: str) -> Plan:
        if goal.startswith("diagnose "):
            return self.validate(
                Plan(
                    goal=goal,
                    steps=[
                        Step(
                            step_id="inspect",
                            objective=goal,
                            call=ToolCall(
                                name="files.search", arguments={"directory": goal[9:].strip()}
                            ),
                        )
                    ],
                )
            )
        if not goal.startswith("organize "):
            raise ToolError("TASK.CLARIFICATION_REQUIRED")
        directory = goal[9:].strip()
        folder = self.actions.scope.path(directory)
        paths = self.actions.scope.search(directory, "", 200)
        steps: list[Step] = []
        groups: dict[str, str] = {}
        for relative in paths:
            source = self.actions.scope.path(relative)
            if source.parent != folder:
                continue
            extension = source.suffix[1:].lower() or "other"
            if not extension.isalnum():
                extension = "other"
            destination_folder = folder / extension
            dependency: list[str] = []
            if not destination_folder.exists():
                if extension not in groups:
                    identifier = f"directory-{len(groups)}"
                    groups[extension] = identifier
                    steps.append(
                        Step(
                            step_id=identifier,
                            objective=f"Create {extension} folder",
                            call=ToolCall(
                                name="directories.create",
                                arguments={
                                    "path": str(
                                        destination_folder.relative_to(self.actions.scope.root)
                                    )
                                },
                            ),
                        )
                    )
                dependency = [groups[extension]]
            steps.append(
                Step(
                    step_id=f"move-{len(steps)}",
                    objective=f"Move {source.name}",
                    dependencies=dependency,
                    call=ToolCall(
                        name="files.move",
                        arguments={
                            "source": relative,
                            "destination": str(
                                (destination_folder / source.name).relative_to(
                                    self.actions.scope.root
                                )
                            ),
                        },
                    ),
                )
            )
        if not steps or len(steps) > 64:
            raise ToolError("TASK.CLARIFICATION_REQUIRED")
        return self.validate(Plan(goal=goal, intent="change", steps=steps))


class Verifier:
    @staticmethod
    def verify(step: Step, status: str, data: dict[str, object]) -> bool:
        return status == "VERIFIED" and (
            step.expected_text is None or step.expected_text in str(data.get("text", ""))
        )


class TaskService:
    def __init__(self, data_dir: Path, actions: ActionService) -> None:
        self.actions = actions
        self.planner = Planner(actions)
        self.path = data_dir / "tasks.sqlite3"
        self.lock_path = data_dir / "tasks-lock.sqlite3"
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, record TEXT NOT NULL)"
            )
            db.execute("PRAGMA user_version=1")
        with closing(sqlite3.connect(self.lock_path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS mutex(id INTEGER PRIMARY KEY)")

    def save(self, task: Task) -> None:
        if contains_secret(task.model_dump_json()):
            raise ToolError("TASK.SECRET_OUTPUT_DENIED")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT record FROM tasks WHERE id=?", (task.task_id,)).fetchone()
            if (
                row
                and Task.model_validate_json(row[0]).status == "CANCELLED"
                and task.status != "CANCELLED"
            ):
                raise ToolError("TASK.CANCELLED")
            db.execute(
                "INSERT INTO tasks VALUES(?,?) ON CONFLICT(id) "
                "DO UPDATE SET record=excluded.record",
                (task.task_id, task.model_dump_json()),
            )
        if self.actions.traces:
            with suppress(OSError, sqlite3.Error, ValueError):
                self.actions.traces.emit(
                    task.task_id,
                    "tasks",
                    "checkpoint",
                    task.status,
                    error_code=task.error_code,
                    references=[task.task_id],
                    metrics={
                        "completed_steps": sum(
                            step.status == "COMPLETED" for step in task.plan.steps
                        ),
                        "steps": len(task.plan.steps),
                        "replans": task.replans,
                    },
                )

    def get(self, identifier: str) -> Task:
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT record FROM tasks WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ToolError("TASK.NOT_FOUND")
        if contains_secret(row[0]):
            raise ToolError("TASK.SECRET_OUTPUT_DENIED")
        return Task.model_validate_json(row[0])

    def list(self) -> list[Task]:
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT id FROM tasks ORDER BY rowid DESC LIMIT 100").fetchall()
        return [self.get(row[0]) for row in rows]

    def create(self, plan: Plan, principal: Principal) -> Task:
        self.actions.permission(principal)
        plan = self.planner.validate(plan.model_copy(deep=True))
        # Bind existing file preconditions into the review digest. Dependent targets may be absent.
        before = {
            str(path): self.actions.scope.stamp(path)
            for step in plan.steps
            for path in self.actions.paths(step.call).values()
        }
        digest = hashlib.sha256(
            json.dumps([plan.model_dump(), before], sort_keys=True).encode()
        ).hexdigest()
        task = Task(
            task_id=new_id(),
            plan=plan,
            digest=digest,
            created_by=principal.person_id,
            created_at=time.time(),
            before=before,
        )
        self.save(task)
        return task

    def approve(self, identifier: str, digest: str, principal: Principal) -> Task:
        self.actions.permission(principal, elevated=True)
        task = self.get(identifier)
        if task.status != "WAITING_FOR_PERMISSION" or task.digest != digest:
            raise ToolError("TASK.APPROVAL_MISMATCH")
        task.approved_until = time.time() + 300
        task.status = "CREATED"
        self.save(task)
        return task

    def cancel(self, identifier: str, principal: Principal) -> Task:
        self.actions.permission(principal)
        task = self.get(identifier)
        if task.status != "COMPLETED":
            task.status = "CANCELLED"
            self.save(task)
        return task

    def run(
        self,
        identifier: str,
        principal: Principal,
        authorize: Callable[[], Principal] | None = None,
    ) -> Task:
        self.actions.permission(principal, elevated=True)
        try:
            with closing(sqlite3.connect(self.lock_path, timeout=0.1)) as lock, lock:
                lock.execute("BEGIN IMMEDIATE")
                started = time.monotonic()
                try:
                    self._execute(identifier, principal, authorize)
                finally:
                    latest = self.get(identifier)
                    latest.elapsed_seconds += time.monotonic() - started
                    self.save(latest)
                return self.get(identifier)
        except ToolError as exc:
            if exc.code == "TASK.CANCELLED":
                return self.get(identifier)
            raise
        except sqlite3.OperationalError:
            raise ToolError("TASK.RESOURCE_BUSY") from None

    def _execute(
        self,
        identifier: str,
        principal: Principal,
        authorize: Callable[[], Principal] | None = None,
    ) -> Task:
        task = self.get(identifier)
        if task.status in {"COMPLETED", "CANCELLED"}:
            return task
        if any(step.status == "UNCERTAIN" for step in task.plan.steps):
            raise ToolError("TASK.RECOVERY_REVIEW_REQUIRED")
        if task.approved_until < time.time():
            raise ToolError("TASK.APPROVAL_REQUIRED")
        if (
            task.status == "CREATED"
            and all(step.status == "WAITING" for step in task.plan.steps)
            and any(
                self.actions.scope.stamp(self.actions.scope.path(path)) != stamp
                for path, stamp in task.before.items()
            )
        ):
            raise ToolError("TASK.STALE_PLAN")
        started = time.monotonic()
        task.status = "RUNNING"
        self.save(task)
        for step in task.plan.steps:
            if self.get(identifier).status == "CANCELLED":
                return self.get(identifier)
            if task.elapsed_seconds + time.monotonic() - started > task.plan.timeout_seconds:
                task.status, task.error_code = "PAUSED", "TASK.TIME_BUDGET"
                self.save(task)
                return task
            if step.status == "COMPLETED":
                continue
            if task.approved_until < time.time():
                task.status, task.error_code = "WAITING_FOR_PERMISSION", "TASK.APPROVAL_EXPIRED"
                task.approved_until = 0
                self.save(task)
                return task
            if authorize:
                principal = authorize()
                self.actions.permission(principal, elevated=True)
            if any(
                item.status != "COMPLETED"
                for item in task.plan.steps
                if item.step_id in step.dependencies
            ):
                task.status, task.error_code = "FAILED", "TASK.DEPENDENCY_FAILED"
                self.save(task)
                return task
            readonly = self.actions.registry.metadata(step.call.name).risk_level < 2
            while step.attempts <= task.plan.retry_limit:
                affected = {
                    str(path)
                    for previous in task.plan.steps
                    if previous.status == "COMPLETED"
                    for path in self.actions.paths(previous.call).values()
                }
                if step.action_id is None and any(
                    str(path) not in affected
                    and self.actions.scope.stamp(path) != task.before.get(str(path), "absent")
                    for path in self.actions.paths(step.call).values()
                ):
                    task.status, task.error_code = "PAUSED", "TASK.STALE_STEP"
                    self.save(task)
                    return task
                step.status = "RUNNING"
                self.save(task)
                call = step.call.model_copy(
                    update={"idempotency_key": f"{identifier}:{step.step_id}:{step.attempts}"}
                )
                try:
                    action = self.actions.preview(call, principal, trace_id=task.task_id)
                    step.action_id = action.action_id
                    self.save(task)
                    if not readonly and action.result.status == "PREVIEW":
                        self.actions.approve(action.action_id, action.digest, principal)
                    action = self.actions.execute(action.action_id, principal)
                    if Verifier.verify(step, action.result.status, action.result.data):
                        step.status = "COMPLETED"
                        self.save(task)
                        break
                    task.error_code = action.result.error_code or "TASK.VERIFICATION_FAILED"
                    if action.result.status == "UNCERTAIN":
                        task.status, step.status = "PAUSED", "UNCERTAIN"
                        self.save(task)
                        return task
                except ToolError as exc:
                    if exc.code == "TOOL.RESOURCE_BUSY":
                        task.status, task.error_code = "WAITING_FOR_RESOURCE", exc.code
                        self.save(task)
                        return task
                    task.error_code = exc.code
                step.attempts += 1
                self.save(task)
                if not readonly:
                    break
            if step.status != "COMPLETED":
                task.status, step.status = "FAILED", "FAILED"
                self.save(task)
                return task
        task.status, task.error_code = "COMPLETED", None
        self.save(task)
        return task

    def replan(self, identifier: str, plan: Plan, principal: Principal) -> Task:
        self.actions.permission(principal)
        old = self.get(identifier)
        if old.status not in {"FAILED", "PAUSED"} or old.replans >= 2:
            raise ToolError("TASK.REPLAN_LIMIT")
        if any(step.status == "UNCERTAIN" for step in old.plan.steps):
            raise ToolError("TASK.RECOVERY_REVIEW_REQUIRED")
        replacement = self.create(plan, principal)
        replacement.replans = old.replans + 1
        self.save(replacement)
        old.status = "PARTIALLY_COMPLETED"
        self.save(old)
        return replacement
