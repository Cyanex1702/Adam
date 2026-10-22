from typing import Literal

from pydantic import Field

from adam.core.contracts import Contract, new_id


class EmptyArgs(Contract):
    pass


class SearchArgs(Contract):
    directory: str = "."
    query: str = Field(default="", max_length=256)
    limit: int = Field(default=100, ge=1, le=200)


class PathArgs(Contract):
    path: str = Field(min_length=1, max_length=1024)


class NoteArgs(PathArgs):
    text: str = Field(min_length=1, max_length=65536)


class MoveArgs(Contract):
    source: str = Field(min_length=1, max_length=1024)
    destination: str = Field(min_length=1, max_length=1024)


class AppArgs(Contract):
    application: Literal["notepad"]


class QueryArgs(Contract):
    query: str = Field(min_length=1, max_length=2048)
    namespace: str = Field(default="default", pattern=r"^[\w-]{1,64}$")


class ToolCall(Contract):
    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, object] = Field(default_factory=dict)
    idempotency_key: str = Field(default_factory=new_id, min_length=1, max_length=128)


class ToolMetadata(Contract):
    name: str
    risk_level: int = Field(ge=0, le=6)
    required_capability: str
    scope: str
    reversible: bool
    verification: str
    supported_devices: list[str] = ["desktop"]
    arguments_schema: dict[str, object]


class ToolResult(Contract):
    action_id: str
    status: Literal[
        "PREVIEW",
        "APPROVED",
        "DENIED",
        "RUNNING",
        "VERIFIED",
        "FAILED",
        "UNCERTAIN",
        "DISPATCHED",
        "UNDONE",
    ]
    tool: str
    data: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None
    epistemic_status: str = "VERIFIED"
