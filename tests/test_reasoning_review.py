import asyncio

import pytest
from adam.core.config import Settings
from adam.core.contracts import AdamError, ErrorEnvelope
from adam.core.runtime import ChatRequest, Runtime
from adam.models.base import ModelCard, ModelHealth, ModelProvider


class ReviewFixture(ModelProvider):
    def __init__(self, *, fail_final=False, secret=False, no_budget=False):
        self.calls = []
        self.fail_final = fail_final
        self.secret = secret
        self.no_budget = no_budget

    def get_capabilities(self):
        return ModelCard(
            provider="fixture",
            model_id="review-fixture",
            display_name="Review fixture",
            quantization="fixture",
            context_limit=8192,
        )

    async def health_check(self):
        return ModelHealth(status="HEALTHY", model_id="review-fixture")

    async def count_tokens(self, messages):
        return 9000 if self.no_budget and "untrusted_draft" in messages[-1].content else 600

    async def stream(self, messages, trace_id):
        self.calls.append(messages)
        if len(self.calls) == 1:
            yield "sk-synthetic-secret-827197411" if self.secret else "Private intermediate draft."
        elif self.fail_final:
            yield "Still incomplete"
            raise AdamError(
                ErrorEnvelope(code="MODEL.RESPONSE_LIMIT", message="Incomplete", trace_id=trace_id)
            )
        else:
            yield "A concise final answer."


def fixture(tmp_path, **options):
    provider = ReviewFixture(**options)
    runtime = Runtime(Settings(data_dir=tmp_path), provider)
    runtime.compute.sampler = lambda: {
        "ram_available_bytes": 4 * 1024**3,
        "ram_used_percent": 50,
        "disk_free_bytes": 4 * 1024**3,
    }
    return runtime, provider


def test_review_draft_is_never_streamed_or_persisted(tmp_path):
    runtime, provider = fixture(tmp_path)

    async def scenario():
        return [
            event
            async for event in runtime.stream(
                ChatRequest(text="Explain this example.", careful=True)
            )
        ]

    events = asyncio.run(scenario())
    assert len(provider.calls) == 2
    assert "explicitly stated facts" in provider.calls[0][-1].content
    assert "original question" in provider.calls[1][-1].content
    assert all("Private intermediate draft" not in str(event.payload) for event in events)
    result = events[-1]
    assert result.event_type == "agent.completed"
    assert result.payload["text"] == "A concise final answer."
    assert result.payload["epistemic_status"] == "UNCERTAIN"
    assert result.payload["review"]["passes"] == 2
    assert "Private intermediate draft" not in str(runtime.store.history(result.session_id))
    runtime.retrieval.close()


@pytest.mark.parametrize(
    "option,code,calls",
    [
        ("secret", "PRIVACY.SECRET_OUTPUT", 1),
        ("no_budget", "MODEL.REVIEW_CONTEXT_LIMIT", 1),
        ("fail_final", "MODEL.RESPONSE_LIMIT", 2),
    ],
)
def test_review_failure_does_not_commit_a_successful_turn(tmp_path, option, code, calls):
    runtime, provider = fixture(tmp_path, **{option: True})
    event = asyncio.run(runtime.chat(ChatRequest(text="Explain this example.", careful=True)))
    assert event.event_type == "agent.error"
    assert event.payload["error"]["code"] == code
    assert len(provider.calls) == calls
    assert runtime.store.history(event.session_id) == []
    runtime.retrieval.close()
