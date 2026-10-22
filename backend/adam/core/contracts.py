from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, NewType
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

SessionId = NewType("SessionId", str)
TraceId = NewType("TraceId", str)
EventId = NewType("EventId", str)
TaskId = NewType("TaskId", str)
ActorId = NewType("ActorId", str)
DeviceId = NewType("DeviceId", str)
DomainId = Annotated[str, Field(min_length=1, max_length=128)]


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EpistemicStatus(StrEnum):
    VERIFIED = "VERIFIED"
    RETRIEVED = "RETRIEVED"
    REPORTED = "REPORTED"
    INFERRED = "INFERRED"
    ASSUMED = "ASSUMED"
    UNCERTAIN = "UNCERTAIN"
    UNKNOWN = "UNKNOWN"


class ErrorEnvelope(Contract):
    code: str
    message: str
    trace_id: TraceId
    severity: str = "ERROR"
    retryable: bool = False
    fallback: str | None = None


class AdamError(Exception):
    def __init__(self, error: ErrorEnvelope) -> None:
        self.error = error
        super().__init__(error.message)


class EventEnvelope(Contract):
    event_id: EventId = Field(default_factory=lambda: EventId(new_id()))
    event_type: str
    timestamp: datetime = Field(default_factory=utc_now)
    trace_id: TraceId
    session_id: SessionId | None = None
    task_id: TaskId | None = None
    actor_id: ActorId = ActorId("local_user")
    device_id: DeviceId = DeviceId("local_desktop")
    sensitivity: str = "INTERNAL"
    payload: dict[str, object] = Field(default_factory=dict)
