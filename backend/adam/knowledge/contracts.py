from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field

from adam.core.contracts import Contract
from adam.security.policy import Mode


class SourcePolicy(Contract):
    profile: Mode = "owner"
    sensitivity: Literal["PUBLIC", "PERSONAL", "PRIVATE", "CONFIDENTIAL", "SECRET", "NEVER_LLM"] = (
        "PERSONAL"
    )
    allowed_audiences: list[str] = Field(default_factory=lambda: ["owner"])
    subjects: list[str] = Field(default_factory=lambda: ["owner"])
    source_actor: str = "local_user"
    disclosure_owner: str = "owner"
    trust: Literal["UNTRUSTED", "OWNER_CURATED"] = "UNTRUSTED"
    replication_policy: str = "local_only"


class SourceRequest(Contract):
    path: str = Field(min_length=1, max_length=4000)
    namespace: str = Field(default="default", pattern=r"^[\w-]{1,64}$")
    policy: SourcePolicy = Field(default_factory=SourcePolicy)


class SourceRecord(Contract):
    source_id: str
    namespace: str
    title: str
    path: str
    media_type: str
    content_hash: str
    version: int
    status: Literal["ACTIVE", "STALE", "MISSING", "BLOCKED"] = "ACTIVE"
    policy: SourcePolicy
    ingested_at: datetime


class ParsedBlock(Contract):
    text: str
    locator: str


class Chunk(Contract):
    chunk_id: str
    source_id: str
    version: int
    ordinal: int
    text: str
    locator: str


class Chunker(Protocol):
    def chunks(self, source_id: str, version: int, blocks: list[ParsedBlock]) -> list[Chunk]: ...
