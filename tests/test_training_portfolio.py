import hashlib
import json
from pathlib import Path

import pytest
from adam.core.storage import ConversationStore
from adam.evals.suite import CaseResult, EvalReport
from adam.portfolio.service import DemoTool, PortfolioError, benchmarks, demo_tool
from adam.training.service import Example, Training, TrainingError, assess
from test_intelligence import personal as personal
from test_intelligence import remember


@pytest.fixture
def training(tmp_path):
    return Training(ConversationStore(tmp_path / "runtime.sqlite3"))


def example(**updates):
    return Example(
        category="formatting",
        prompt="Return a fictional color as JSON.",
        response='{"color":"blue"}',
        approved=True,
        synthetic_behavior_only=True,
        permission_to_export=True,
        **updates,
    )


def report(real=True, failures=(), model="base"):
    cases = [
        CaseResult(
            name=f"case-{i}",
            category="formatting" if i < 2 else "security",
            passed=i not in failures,
            critical=i >= 2,
            duration_ms=1,
        )
        for i in range(22)
    ]
    return EvalReport(
        suite="full-v1",
        dataset_digest="synthetic-test-digest",
        model={"model_id": model},
        execution="real-model;keyword-rag" if real else "scripted-framework-probe;keyword-rag",
        passed=not failures,
        critical_failures=sum(i >= 2 for i in failures),
        cases=cases,
        scores={},
        note="synthetic unit fixture",
    )


def test_training_disabled_by_default_and_explicit_approval_needed(training):
    assert not training.status()["enabled"]
    with pytest.raises(TrainingError):
        training.add(example())
    with pytest.raises(ValueError):
        Example(
            category="formatting",
            prompt="x",
            response="y",
            approved=False,
            synthetic_behavior_only=True,
            permission_to_export=True,
        )


def test_dataset_is_deterministic_and_only_contains_approved_examples(training):
    training.configure(True)
    item = example()
    training.add(item)
    first = training.dataset()
    assert first == training.dataset()
    assert first["sha256"] == hashlib.sha256(first["jsonl"].encode()).hexdigest()
    assert json.loads(first["jsonl"])["messages"][0]["content"] == item.prompt
    training.remove(item.id)
    with pytest.raises(TrainingError):
        training.dataset()


@pytest.mark.parametrize(
    "text", ["password=fictional-password-value", "Bearer syntheticCredentialValue12345", "   "]
)
def test_training_refuses_credentials_and_blank_content(training, text):
    training.configure(True)
    value = example().model_copy(update={"prompt": text})
    with pytest.raises(TrainingError):
        training.add(value)


def test_disable_revokes_dataset_access(training):
    training.configure(True)
    training.add(example())
    training.configure(False)
    with pytest.raises(TrainingError):
        training.dataset()


def test_known_personal_memory_cannot_be_exported(personal):
    service, _ = personal
    source = remember(personal)
    training = Training(service.store)
    training.configure(True)
    with pytest.raises(TrainingError, match="PERSONAL_MEMORY_OVERLAP"):
        training.add(example().model_copy(update={"response": source.content}))


def test_only_real_comparable_improved_reports_reach_human_review():
    base, candidate = report(failures=(0,)), report(model="adapter")
    result = assess(base, candidate, "formatting")
    assert result["status"] == "HUMAN_REVIEW_REQUIRED" and result["target_delta"] == 0.5
    assert not result["adapter_activated"]
    assert (
        assess(report(), report(model="adapter"), "formatting")["status"] == "REJECTED_OR_DEFERRED"
    )


@pytest.mark.parametrize(
    "change", ["fixture", "digest", "regression", "same_model", "duplicate", "missing_cases"]
)
def test_misleading_or_regressed_comparisons_rejected(change):
    base, candidate = report(failures=(0,)), report(model="adapter")
    if change == "fixture":
        base.execution = candidate.execution = "scripted-framework-probe;keyword-rag"
    elif change == "digest":
        candidate.dataset_digest = "different"
    elif change == "regression":
        candidate.cases[4].passed = False
        candidate.critical_failures = 0  # A forged summary cannot override case outcomes.
    elif change == "same_model":
        candidate.model = base.model
    elif change == "duplicate":
        candidate.cases[-1] = candidate.cases[0]
    else:
        candidate.cases.pop()
    assert assess(base, candidate, "formatting")["status"] == "REJECTED_OR_DEFERRED"


def test_demo_tool_writes_verifies_and_undoes_only_its_profile(tmp_path):
    owner = tmp_path / "owner.txt"
    owner.write_text("SYNTHETIC OWNER SENTINEL", encoding="utf-8")
    root = tmp_path / "demo"
    result = demo_tool(root, DemoTool(action="write_note", text="Fictional note"))
    assert result["status"] == "VERIFIED"
    assert demo_tool(root, DemoTool(action="inspect"))["text"] == "Fictional note"
    assert demo_tool(root, DemoTool(action="undo_note"))["status"] == "UNDONE"
    assert not demo_tool(root, DemoTool(action="inspect"))["files"]
    assert owner.read_text(encoding="utf-8") == "SYNTHETIC OWNER SENTINEL"


def test_demo_tool_refuses_overwrite_and_changed_undo(tmp_path):
    demo_tool(tmp_path, DemoTool(action="write_note"))
    with pytest.raises(PortfolioError, match="UNDO_PENDING"):
        demo_tool(tmp_path, DemoTool(action="write_note"))
    (tmp_path / "portfolio-sandbox/fictional-note.txt").write_text(
        "Changed externally", encoding="utf-8"
    )
    with pytest.raises(PortfolioError, match="CHANGED_SINCE_WRITE"):
        demo_tool(tmp_path, DemoTool(action="undo_note"))


def test_demo_tool_denies_secrets_and_arbitrary_actions(tmp_path):
    with pytest.raises(PortfolioError):
        demo_tool(tmp_path, DemoTool(action="write_note", text="password=fictional-value-1234"))
    with pytest.raises(ValueError):
        DemoTool(action="shell.exec")


def test_benchmark_dashboard_derives_rates_from_cases(tmp_path):
    path = tmp_path / "report.json"
    fixture = report(real=False, failures=(0,))
    fixture.scores = {"formatting": 1.0}  # Misleading supplied aggregate must be ignored.
    path.write_text(fixture.model_dump_json(), encoding="utf-8")
    result = benchmarks(path)
    assert result["categories"]["formatting"]["rate"] == 0.5
    assert result["vram_bytes"] is None and result["voice_metrics"] is None
    assert "scripted" in result["execution"] and not any(
        "trace_ids" in case for case in result["cases"]
    )


def test_absent_or_corrupt_benchmarks_never_fabricate_metrics(tmp_path):
    path = tmp_path / "report.json"
    assert benchmarks(path)["status"] == "UNAVAILABLE"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(PortfolioError):
        benchmarks(path)


def test_recipe_is_valid_python_and_never_contains_owner_data():
    path = Path(__file__).parents[1] / "backend/adam/training/recipe.txt"
    text = path.read_text(encoding="utf-8")
    compile(text, str(path), "exec")
    assert "trust_remote_code=False" in text and "EXPERIMENT_ONLY_NOT_PROMOTED" in text
    assert "runtime.sqlite3" not in text
