import asyncio
import json

import httpx
import pytest
from adam.core.config import ModelConfig
from adam.core.contracts import AdamError, TraceId, new_id
from adam.models.base import Message, closing_stream
from adam.models.llama_cpp import LlamaCppProvider


def token(text):
    return ("data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n\n").encode()


class SlowStream(httpx.AsyncByteStream):
    def __init__(self, plan):
        self.plan, self.closed = plan, False

    async def __aiter__(self):
        for delay, data in self.plan:
            await asyncio.sleep(delay)
            yield data

    async def aclose(self):
        self.closed = True


def provider(stream, first=0.2, idle=0.02, headers=0):
    async def respond(request):
        await asyncio.sleep(headers)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    return LlamaCppProvider(
        ModelConfig(first_token_timeout_seconds=first, timeout_seconds=idle),
        httpx.MockTransport(respond),
    )


def test_first_reply_gets_prefill_budget_including_delayed_headers():
    stream = SlowStream([(0.03, token("Hello")), (0, b"data: [DONE]\n\n")])
    adapter = provider(stream, first=0.5, idle=0.01, headers=0.03)
    assert (
        asyncio.run(adapter.generate([Message(role="user", content="hi")], TraceId(new_id())))
        == "Hello"
    )
    assert stream.closed


@pytest.mark.parametrize("headers", [False, True])
def test_silent_first_reply_has_a_finite_deadline(headers):
    stream = SlowStream([(0.2, token("late"))])
    adapter = provider(stream, first=0.03, headers=0.2 if headers else 0)
    with pytest.raises(AdamError) as failure:
        asyncio.run(adapter.generate([Message(role="user", content="hi")], TraceId(new_id())))
    assert failure.value.error.code == "MODEL.TIMEOUT"
    if not headers:
        assert stream.closed


def test_heartbeats_do_not_reset_first_text_deadline():
    stream = SlowStream([(0.01, b": keepalive\n\n")] * 100)
    adapter = provider(stream, first=0.03)
    with pytest.raises(AdamError) as failure:
        asyncio.run(adapter.generate([Message(role="user", content="hi")], TraceId(new_id())))
    assert failure.value.error.code == "MODEL.TIMEOUT"
    assert stream.closed


def test_stalled_reply_uses_idle_budget_and_closes_partial_stream():
    stream = SlowStream([(0, token("partial")), (0.3, token("late"))])
    adapter = provider(stream, first=1, idle=0.03)

    async def run():
        chunks = []
        with pytest.raises(AdamError) as failure:
            async with closing_stream(adapter.stream([], TraceId(new_id()))) as answer:
                async for chunk in answer:
                    chunks.append(chunk)
        assert failure.value.error.code == "MODEL.TIMEOUT"
        assert chunks == ["partial"]

    asyncio.run(run())
    assert stream.closed


def test_stop_cancels_first_reply_wait_and_closes_connection():
    stream = SlowStream([(10, token("never shown"))])
    adapter = provider(stream, first=30)

    async def run():
        async with closing_stream(adapter.stream([], TraceId(new_id()))) as answer:
            task = asyncio.create_task(anext(answer))
            await asyncio.sleep(0.02)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())
    assert stream.closed


def test_saved_legacy_profile_gets_first_reply_budget_without_overwriting_idle_limit():
    config = ModelConfig.model_validate({"timeout_seconds": 75})
    assert config.timeout_seconds == 75
    assert config.first_token_timeout_seconds == 300
    # Timing settings are transport policy, not advertised model capabilities.
    assert (
        "first_token_timeout_seconds"
        not in LlamaCppProvider(config).get_capabilities().model_dump()
    )


def test_partial_timeout_is_not_saved_as_a_completed_conversation(tmp_path):
    from adam.core.config import Settings
    from adam.core.runtime import ChatRequest, Runtime

    stream = SlowStream([(0, token("partial synthetic reply")), (1, token("late"))])

    async def respond(request):
        if request.url.path == "/health":
            return httpx.Response(200)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen3-8b"}]})
        if request.url.path != "/v1/chat/completions":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    adapter = LlamaCppProvider(
        ModelConfig(first_token_timeout_seconds=1, timeout_seconds=0.03),
        httpx.MockTransport(respond),
    )
    runtime = Runtime(Settings(data_dir=tmp_path), adapter)
    try:
        result = asyncio.run(runtime.chat(ChatRequest(text="synthetic greeting")))
        assert result.event_type == "agent.error"
        assert result.payload["error"]["code"] == "MODEL.TIMEOUT"
        assert runtime.store.history(result.session_id) == []
        assert stream.closed
    finally:
        runtime.retrieval.close()
