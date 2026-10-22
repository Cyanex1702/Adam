from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from adam.core.contracts import Contract


class MeshError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Packet(Contract):
    message: str = Field(min_length=1, max_length=3_500_000)
    signature: str = Field(min_length=1, max_length=128)


class Request(Contract):
    protocol: Literal[1]
    device_id: UUID
    request_id: UUID
    issued_at: int
    operation: Literal[
        "status", "new_session", "session", "chat", "search", "handoff", "transcribe", "speak"
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class Claim(Contract):
    protocol: Literal[1]
    code: str = Field(pattern=r"^[a-f0-9]{24}$")
    label: str = Field(min_length=1, max_length=48, pattern=r"^[\w .'-]+$")
    public_key: str = Field(max_length=256)
    signature: str = Field(max_length=128)


class Approval(Contract):
    device_id: UUID
    search: bool = False
    voice: bool = False


class Device(Contract):
    device_id: UUID


class Share(Contract):
    device_id: UUID
    session_id: UUID
    consent: Literal[True]


class Handoff(Contract):
    session_id: UUID
    primary: str = Field(pattern=r"^(desktop|[a-f0-9-]{36})$")
