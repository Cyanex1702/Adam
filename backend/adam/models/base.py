from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from adam.core.contracts import Contract, TraceId


@asynccontextmanager
async def closing_stream(stream: AsyncIterator[str]) -> AsyncIterator[AsyncIterator[str]]:
    try:
        yield stream
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()


class Message(Contract):
    role: Literal["system", "user", "assistant"]
    content: str


class ModelCard(Contract):
    model_id: str
    display_name: str
    provider: str
    quantization: str
    context_limit: int
    modality: str = "text"
    tools: bool = False
    reasoning: bool = False
    json_output: bool = False
    languages: list[str] = []
    metadata_source: str = "configured; runtime alias checked by health"


class ModelHealth(Contract):
    status: Literal["HEALTHY", "DEGRADED", "FAILED", "DISABLED"]
    model_id: str
    reason: str | None = None


class ModelProvider(ABC):
    @abstractmethod
    def get_capabilities(self) -> ModelCard: ...

    @abstractmethod
    async def health_check(self) -> ModelHealth: ...

    @abstractmethod
    def stream(self, messages: list[Message], trace_id: TraceId) -> AsyncIterator[str]: ...

    async def generate(self, messages: list[Message], trace_id: TraceId) -> str:
        return "".join([chunk async for chunk in self.stream(messages, trace_id)])

    def supports_tools(self) -> bool:
        return self.get_capabilities().tools

    def supports_reasoning(self) -> bool:
        return self.get_capabilities().reasoning

    def supports_json(self) -> bool:
        return self.get_capabilities().json_output

    def get_context_limit(self) -> int:
        return self.get_capabilities().context_limit

    async def count_tokens(self, messages: list[Message]) -> int:
        """Conservative UTF-8 byte upper bound, not tokenizer measurement."""
        return sum(len(m.content.encode("utf-8")) + 32 for m in messages) + 128

    async def load(self) -> ModelHealth:
        """Attach to an externally managed runtime; never download automatically."""
        return await self.health_check()

    async def unload(self) -> None:
        """Release adapter resources; never kill the external model server."""
        return None


class ModelRegistry:
    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def cards(self) -> list[ModelCard]:
        return [self.provider.get_capabilities()]
