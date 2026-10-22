import asyncio
import getpass
import json
from dataclasses import replace
from typing import TYPE_CHECKING

from pydantic import ValidationError

from adam.security.auth import AuthError, AuthManager
from adam.tasks.service import Plan
from adam.tools.contracts import ToolCall
from adam.tools.registry import ToolError

if TYPE_CHECKING:
    from adam.core.runtime import Runtime


async def handle_command(text: str, runtime: "Runtime", auth: AuthManager) -> bool:
    command, _, argument = text.partition(" ")
    if command not in {
        "/tools",
        "/tool",
        "/actions",
        "/undo",
        "/approve-action",
        "/deny-action",
        "/run-action",
        "/plan",
        "/task-json",
        "/tasks",
        "/approve-task",
        "/run-task",
        "/cancel-task",
    }:
        return False
    principal = runtime.principal
    try:
        if command in {"/approve-action", "/run-action", "/approve-task", "/run-task"}:
            runtime.actions.permission(principal)
            password = await asyncio.to_thread(getpass.getpass, "Owner passphrase: ")
            try:
                await asyncio.to_thread(auth.verify, password)
            finally:
                password = ""
            principal = replace(principal, elevated=True)
        if command == "/tools":
            print(
                json.dumps(
                    {
                        "scope": str(runtime.actions.scope.root),
                        "tools": [item.model_dump() for item in runtime.actions.registry.list()],
                    },
                    indent=2,
                )
            )
        elif command == "/tool":
            action = runtime.actions.preview(ToolCall.model_validate_json(argument), principal)
            if runtime.actions.registry.metadata(action.call.name).risk_level < 2:
                action = await asyncio.to_thread(
                    runtime.actions.execute, action.action_id, principal
                )
            print(action.model_dump_json(indent=2))
        elif command == "/actions":
            print(
                json.dumps(
                    [item.model_dump(mode="json") for item in runtime.actions.list()], indent=2
                )
            )
        elif command == "/undo":
            print(runtime.actions.undo(argument.strip(), principal).model_dump_json(indent=2))
        elif command in {"/approve-action", "/deny-action"}:
            identifier, digest = argument.split()
            print(
                runtime.actions.approve(
                    identifier, digest, principal, command == "/approve-action"
                ).model_dump_json(indent=2)
            )
        elif command == "/run-action":
            print(
                (
                    await asyncio.to_thread(runtime.actions.execute, argument.strip(), principal)
                ).model_dump_json(indent=2)
            )
        elif command in {"/plan", "/task-json"}:
            runtime.actions.permission(principal)
            plan = (
                runtime.tasks.planner.from_goal(argument)
                if command == "/plan"
                else Plan.model_validate_json(argument)
            )
            print(runtime.tasks.create(plan, principal).model_dump_json(indent=2))
        elif command == "/tasks":
            print(
                json.dumps(
                    [item.model_dump(mode="json") for item in runtime.tasks.list()], indent=2
                )
            )
        elif command == "/approve-task":
            identifier, digest = argument.split()
            print(runtime.tasks.approve(identifier, digest, principal).model_dump_json(indent=2))
        elif command == "/run-task":
            print(
                (
                    await asyncio.to_thread(runtime.tasks.run, argument.strip(), principal)
                ).model_dump_json(indent=2)
            )
        elif command == "/cancel-task":
            print(runtime.tasks.cancel(argument.strip(), principal).model_dump_json(indent=2))
    except (ToolError, AuthError) as exc:
        print(f"[{exc.code}]")
    except (ValueError, ValidationError):
        print("[TOOL.INVALID_COMMAND]")
    return True
