from pydantic import ValidationError

from adam.core.contracts import Contract
from adam.core.privacy import contains_secret
from adam.tools.contracts import (
    AppArgs,
    EmptyArgs,
    MoveArgs,
    NoteArgs,
    PathArgs,
    QueryArgs,
    SearchArgs,
    ToolCall,
    ToolMetadata,
)


class ToolError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


DEFINITIONS: dict[str, tuple[type[Contract], int, str, str, bool, str]] = {
    "system.info": (EmptyArgs, 0, "system.observe", "public_system_metadata", False, "observed"),
    "files.search": (SearchArgs, 1, "filesystem.read", "sandbox", False, "scoped_paths"),
    "files.read": (PathArgs, 1, "filesystem.read", "sandbox", False, "content_hash"),
    "files.open": (PathArgs, 2, "desktop.open_file", "sandbox", False, "dispatch_only"),
    "apps.open": (
        AppArgs,
        2,
        "desktop.open_application",
        "fixed_application_allowlist",
        False,
        "dispatch_only",
    ),
    "notes.create": (NoteArgs, 3, "filesystem.write", "sandbox", True, "content_hash"),
    "directories.create": (PathArgs, 3, "filesystem.write", "sandbox", True, "directory_exists"),
    "directories.remove_empty": (
        PathArgs,
        4,
        "filesystem.write",
        "sandbox",
        False,
        "directory_absent",
    ),
    "files.move": (MoveArgs, 4, "filesystem.write", "sandbox", True, "file_identity_and_hash"),
    "files.quarantine": (
        PathArgs,
        5,
        "filesystem.quarantine",
        "sandbox",
        True,
        "file_identity_and_hash",
    ),
    "memory.search": (QueryArgs, 1, "memory.read", "current_profile", False, "policy_filtered"),
    "knowledge.search": (
        QueryArgs,
        1,
        "knowledge.read",
        "current_profile",
        False,
        "policy_filtered",
    ),
}


class ToolRegistry:
    def metadata(self, name: str) -> ToolMetadata:
        if name not in DEFINITIONS:
            raise ToolError("TOOL.NOT_REGISTERED")
        args, risk, capability, scope, reversible, verification = DEFINITIONS[name]
        return ToolMetadata(
            name=name,
            risk_level=risk,
            required_capability=capability,
            scope=scope,
            reversible=reversible,
            verification=verification,
            arguments_schema=args.model_json_schema(),
        )

    def list(self) -> list[ToolMetadata]:
        return [self.metadata(name) for name in DEFINITIONS]

    def validate(self, call: ToolCall) -> ToolCall:
        self.metadata(call.name)
        if contains_secret(call.model_dump_json()):
            raise ToolError("TOOL.SECRET_INPUT_DENIED")
        try:
            args = DEFINITIONS[call.name][0].model_validate(call.arguments)
        except ValidationError:
            raise ToolError("TOOL.INVALID_ARGUMENTS") from None
        return call.model_copy(update={"arguments": args.model_dump()})
