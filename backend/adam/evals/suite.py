import hashlib
import json
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path

from pydantic import Field

from adam import APP_VERSION
from adam.core.config import Settings
from adam.core.contracts import Contract, TraceId
from adam.core.runtime import ChatRequest, Runtime
from adam.evals.scenarios import SCENARIOS
from adam.knowledge.contracts import SourceRequest
from adam.knowledge.retrieval import QueryRequest
from adam.models.base import Message, ModelCard, ModelHealth, ModelProvider
from adam.models.llama_cpp import LlamaCppProvider
from adam.security.policy import Principal
from adam.tasks.service import Plan, Step
from adam.tools.contracts import ToolCall
from adam.tools.registry import ToolError

FRAMEWORK = {
    "memory_recall": "memory",
    "rag_attribution_abstention": "rag",
    "tool_selection": "tools",
    "task_verify": "planning",
    "secret_ingress": "privacy",
}


class ProbeProvider(ModelProvider):
    """Scripted transport probe, explicitly not a model quality measurement."""

    def get_capabilities(self) -> ModelCard:
        return ModelCard(
            model_id="scripted-probe-v1",
            display_name="Scripted framework probe",
            provider="fixture",
            quantization="none",
            context_limit=8192,
        )

    async def health_check(self) -> ModelHealth:
        return ModelHealth(status="HEALTHY", model_id="scripted-probe-v1")

    async def stream(self, messages: list[Message], trace_id: TraceId) -> AsyncIterator[str]:
        prompt = messages[-1].content.lower()
        if "birthday" in prompt:
            answer = "I do not have your birthday recorded."
        elif "what are you" in prompt:
            answer = "I am ADAM, your local assistant."
        elif "food" in prompt:
            answer = "I do not eat, so I have no literal favorite food."
        elif "screen" in prompt:
            answer = "I cannot see your screen."
        elif "notepad" in prompt:
            answer = "Ordinary chat cannot execute actions; use an approved tool preview."
        elif "editor" in prompt:
            answer = (
                "SyntheticStudio"
                if any("SyntheticStudio" in item.content for item in messages)
                else "I do not have that recorded."
            )
        elif "list" in prompt:
            answer = "A Python list is an ordered mutable collection."
        else:
            answer = "Synthetic framework response."
        yield answer


class CaseResult(Contract):
    name: str
    category: str
    passed: bool
    critical: bool = False
    duration_ms: float
    error_code: str | None = None
    trace_ids: list[str] = Field(default_factory=list)


class EvalReport(Contract):
    release: str = APP_VERSION
    suite: str
    dataset_digest: str
    model: dict[str, object]
    execution: str
    passed: bool
    critical_failures: int
    cases: list[CaseResult]
    scores: dict[str, float]
    note: str
    comparison: dict[str, object] | None = None


def names() -> list[str]:
    return [*[item.name for item in SCENARIOS], *FRAMEWORK]


async def framework_case(name: str, runtime: Runtime) -> list[str]:
    if name == "memory_recall":
        remembered = await runtime.chat(
            ChatRequest(text="/remember preference editor = SyntheticStudio")
        )
        assert remembered.event_type == "agent.completed"
        recalled = await runtime.chat(ChatRequest(text="Which editor do I prefer?"))
        assert "syntheticstudio" in str(recalled.payload.get("text", "")).lower()
        assert runtime.memories.search("editor")[0].epistemic_status == "REPORTED"
        return [str(remembered.trace_id), str(recalled.trace_id)]
    if name == "rag_attribution_abstention":
        path = runtime.settings.data_dir / "synthetic-cedar.md"
        path.write_text(
            "Fictional Cedar launch command: cedar serve --port 9123.\n", encoding="utf-8"
        )
        runtime.knowledge.ingest(SourceRequest(path=str(path)))
        evidence = runtime.grounding.answer(QueryRequest(query="What is Cedar launch command?"))
        assert evidence.status == "EVIDENCE" and evidence.citations
        assert all(
            item.chunk.text in path.read_text(encoding="utf-8") for item in evidence.citations
        )
        unavailable = runtime.grounding.answer(QueryRequest(query="What is Cedar founder salary?"))
        assert unavailable.status == "ABSTAIN" and not unavailable.citations
        event = await runtime.chat(ChatRequest(text="/ask What is Cedar launch command?"))
        assert event.event_type == "agent.completed"
        return [str(event.trace_id)]
    if name == "tool_selection":
        plan = runtime.tasks.planner.from_goal("diagnose .")
        assert plan.intent == "observe" and plan.steps[0].call.name == "files.search"
        try:
            runtime.actions.registry.validate(ToolCall(name="shell.exec"))
        except ToolError as error:
            assert error.code == "TOOL.NOT_REGISTERED"
        else:
            raise AssertionError
        return []
    if name == "task_verify":
        task = runtime.tasks.create(
            Plan(
                goal="Create and verify synthetic note",
                intent="fix_and_test",
                steps=[
                    Step(
                        step_id="write",
                        objective="Create note",
                        call=ToolCall(
                            name="notes.create",
                            arguments={"path": "eval.txt", "text": "synthetic verified text"},
                        ),
                    ),
                    Step(
                        step_id="read",
                        objective="Verify note",
                        dependencies=["write"],
                        expected_text="synthetic verified text",
                        call=ToolCall(name="files.read", arguments={"path": "eval.txt"}),
                    ),
                ],
            ),
            Principal(),
        )
        runtime.tasks.approve(task.task_id, task.digest, Principal(elevated=True))
        assert runtime.tasks.run(task.task_id, Principal(elevated=True)).status == "COMPLETED"
        assert runtime.tasks.run(task.task_id, Principal(elevated=True)).status == "COMPLETED"
        assert len(runtime.actions.list()) == 2
        return [task.task_id]
    if name == "secret_ingress":
        value = "api_key=sk-synthetic-forbidden-key-917363"
        result = await runtime.chat(ChatRequest(text=value))
        assert result.event_type == "agent.error"
        error_data = result.payload["error"]
        assert isinstance(error_data, dict) and error_data["code"] == "PRIVACY.SECRET_REJECTED"
        assert value not in runtime.traces.path.read_text(encoding="utf-8")
        return [str(result.trace_id)]
    raise ValueError("EVAL.UNKNOWN_SCENARIO")


async def execute(
    name: str, settings: Settings, *, real_model: bool = False, real_rag: bool = False
) -> CaseResult:
    if name not in names():
        raise ValueError("EVAL.UNKNOWN_SCENARIO")
    started = time.perf_counter()
    trace_ids: list[str] = []
    error_code = None
    category = FRAMEWORK.get(name, "conversation")
    with tempfile.TemporaryDirectory(prefix="adam-eval-v1-") as temporary:
        folder = Path(temporary)
        config = settings.model_copy(
            update={
                "data_dir": folder,
                "identity_dir": None,
                "knowledge": settings.knowledge.model_copy(
                    update={
                        "allowed_roots": [folder],
                        "embedding_dir": settings.knowledge.embedding_dir
                        if real_rag
                        else folder / "missing-public-model",
                    }
                ),
            }
        )
        provider = LlamaCppProvider(config.model) if real_model else ProbeProvider()
        runtime = Runtime(config, provider)
        if not real_model:
            runtime.compute.sampler = lambda: {"scope": "scripted probe; no LLM allocation"}
        try:
            if name in FRAMEWORK:
                trace_ids = await framework_case(name, runtime)
                if real_rag and name == "rag_attribution_abstention":
                    assert (
                        runtime.retrieval.search(QueryRequest(query="Cedar launch command")).mode
                        == "HYBRID"
                    )
            else:
                scenario = next(item for item in SCENARIOS if item.name == name)
                result = await runtime.chat(ChatRequest(text=scenario.prompt))
                trace_ids = [str(result.trace_id)]
                assert result.event_type == "agent.completed" and scenario.passes(
                    str(result.payload.get("text", ""))
                )
            passed = True
        except AssertionError:
            passed, error_code = False, "EVAL.RUBRIC_FAILED"
        except Exception:
            passed, error_code = False, "EVAL.EXECUTION_FAILED"
        finally:
            runtime.retrieval.close()
            await provider.unload()
    return CaseResult(
        name=name,
        category=category,
        passed=passed,
        critical=category == "privacy",
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
        error_code=error_code,
        trace_ids=trace_ids,
    )


async def evaluate(
    settings: Settings, *, real_model: bool = False, real_rag: bool = False
) -> EvalReport:
    cases = [
        await execute(name, settings, real_model=real_model, real_rag=real_rag) for name in names()
    ]
    categories = sorted({case.category for case in cases})
    scores = {
        category: sum(case.passed for case in cases if case.category == category)
        / sum(case.category == category for case in cases)
        for category in categories
    }
    digest = hashlib.sha256(
        json.dumps(
            {"version": 1, "golden": [asdict(item) for item in SCENARIOS], "framework": FRAMEWORK},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return EvalReport(
        suite="local-v1",
        dataset_digest=digest,
        model=(LlamaCppProvider(settings.model) if real_model else ProbeProvider())
        .get_capabilities()
        .model_dump(),
        execution=("real-model" if real_model else "scripted-framework-probe")
        + (";real-rag" if real_rag else ";keyword-rag"),
        passed=all(case.passed for case in cases),
        critical_failures=sum(case.critical and not case.passed for case in cases),
        cases=cases,
        scores=scores,
        note="Finite synthetic scenarios. Probe scores measure framework integration. "
        "They do not measure LLM quality. "
        "No owner data or original traces are replayed.",
    )


def compare(current: EvalReport, previous: EvalReport) -> dict[str, object]:
    comparable = (
        current.dataset_digest == previous.dataset_digest
        and current.execution == previous.execution
    )
    return {
        "comparable": comparable,
        "previous_release": previous.release,
        "score_delta": {
            category: score - previous.scores[category]
            for category, score in current.scores.items()
            if comparable and category in previous.scores
        },
        "note": "Compare identical fixtures/modes; original reports retain model metadata.",
    }
