import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack

import httpx

from adam.core.config import ModelConfig
from adam.core.contracts import AdamError, ErrorEnvelope, TraceId
from adam.models.base import Message, ModelCard, ModelHealth, ModelProvider


class LlamaCppProvider(ModelProvider):
    def __init__(
        self, config: ModelConfig, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.config = config
        self.transport = transport

    def get_capabilities(self) -> ModelCard:
        return ModelCard(
            **self.config.model_dump(
                exclude={
                    "base_url",
                    "max_tokens",
                    "timeout_seconds",
                    "first_token_timeout_seconds",
                    "temperature",
                    "seed",
                }
            )
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.config.base_url,
            trust_env=False,
            timeout=self.config.timeout_seconds,
            transport=self.transport,
            follow_redirects=False,
        )

    async def health_check(self) -> ModelHealth:
        try:
            async with self._client() as client:
                response = await client.get("/health", timeout=5)
                response.raise_for_status()
                models = await client.get("/v1/models", timeout=5)
                models.raise_for_status()
                matching = [
                    item for item in models.json()["data"] if item["id"] == self.config.model_id
                ]
                if not matching:
                    return ModelHealth(
                        status="DEGRADED",
                        model_id=self.config.model_id,
                        reason="MODEL.IDENTITY_MISMATCH",
                    )
                runtime_context = matching[0].get("meta", {}).get("n_ctx")
                if isinstance(runtime_context, int) and runtime_context < self.config.context_limit:
                    return ModelHealth(
                        status="DEGRADED",
                        model_id=self.config.model_id,
                        reason="MODEL.CONTEXT_MISMATCH",
                    )
            return ModelHealth(status="HEALTHY", model_id=self.config.model_id)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return ModelHealth(
                status="DEGRADED", model_id=self.config.model_id, reason="MODEL.UNAVAILABLE"
            )

    async def count_tokens(self, messages: list[Message]) -> int:
        try:
            async with self._client() as client:
                template = await client.post(
                    "/apply-template",
                    json={"messages": [message.model_dump() for message in messages]},
                )
                template.raise_for_status()
                prompt = template.json()["prompt"]
                if not isinstance(prompt, str):
                    raise ValueError("Invalid template")
                response = await client.post(
                    "/tokenize",
                    json={"content": prompt, "add_special": True, "parse_special": True},
                )
                response.raise_for_status()
                tokens = response.json()["tokens"]
                if not isinstance(tokens, list) or not all(type(t) is int for t in tokens):
                    raise ValueError("Invalid tokens")
                return len(tokens) + 32  # Reserve template/generation overhead.
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return await super().count_tokens(messages)

    async def stream(self, messages: list[Message], trace_id: TraceId) -> AsyncIterator[str]:
        code = "MODEL.UNAVAILABLE"
        emitted = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.first_token_timeout_seconds
        try:
            async with self._client() as client, AsyncExitStack() as responses:
                # Bound connection/header wait without holding a timeout scope over yield.
                async with asyncio.timeout_at(deadline):
                    response = await responses.enter_async_context(
                        client.stream(
                            "POST",
                            "/v1/chat/completions",
                            json={
                                "model": self.config.model_id,
                                "messages": [m.model_dump() for m in messages],
                                "stream": True,
                                "max_tokens": self.config.max_tokens,
                                "temperature": self.config.temperature,
                                **(
                                    {"seed": self.config.seed}
                                    if self.config.seed is not None
                                    else {}
                                ),
                            },
                            timeout=httpx.Timeout(
                                connect=5,
                                write=10,
                                pool=5,
                                read=max(
                                    self.config.first_token_timeout_seconds,
                                    self.config.timeout_seconds,
                                ),
                            ),
                        )
                    )
                if response.status_code >= 500:
                    async with asyncio.timeout_at(deadline):
                        body = (await response.aread())[:65536].lower()
                    if any(marker in body for marker in [b"out of memory", b"cuda out", b"oom"]):
                        raise AdamError(
                            ErrorEnvelope(
                                code="MODEL.OOM",
                                trace_id=trace_id,
                                message="Model allocation failed; explicit recovery required.",
                            )
                        )
                response.raise_for_status()
                code = "MODEL.PROTOCOL_ERROR"
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise ValueError("Expected SSE")
                lines = response.aiter_lines().__aiter__()
                while True:
                    # SSE heartbeats/reasoning fields cannot extend a silent reply forever.
                    async with asyncio.timeout_at(deadline):
                        try:
                            line = await anext(lines)
                        except StopAsyncIteration:
                            break
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        if not emitted:
                            raise ValueError("No answer")
                        return
                    packet = json.loads(data)
                    if packet.get("error"):
                        raise ValueError("Runtime error")
                    choices = packet.get("choices", [])
                    if not choices:
                        continue
                    if choices[0].get("finish_reason") == "length":
                        raise AdamError(
                            ErrorEnvelope(
                                code="MODEL.RESPONSE_LIMIT",
                                message="Token limit reached. Partial response is incomplete.",
                                trace_id=trace_id,
                                retryable=True,
                            )
                        )
                    content = choices[0].get("delta", {}).get("content")
                    # Reasoning and tool-call fields are never forwarded or logged.
                    if content is not None:
                        if not isinstance(content, str):
                            raise ValueError("Invalid token")
                        if content:
                            emitted = True
                            deadline = loop.time() + self.config.timeout_seconds
                            yield content
                raise ValueError("Missing completion marker")
        except AdamError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise AdamError(
                ErrorEnvelope(
                    code="MODEL.TIMEOUT",
                    trace_id=trace_id,
                    message=(
                        "The local model stalled while replying. This turn was not saved."
                        if emitted
                        else "The local model did not produce its first reply in time. "
                        "This turn was not saved."
                    ),
                    retryable=True,
                )
            ) from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise AdamError(
                ErrorEnvelope(
                    code=code,
                    trace_id=trace_id,
                    message="The local model is unavailable or returned an invalid stream.",
                    retryable=True,
                    fallback="Check the llama.cpp server and retry.",
                )
            ) from None
