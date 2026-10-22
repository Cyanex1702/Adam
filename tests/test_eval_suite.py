import asyncio
import json

import pytest
from adam.api.app import create_app
from adam.core.config import Settings
from adam.evals.suite import compare, evaluate, execute, names
from fastapi.testclient import TestClient
from test_text_runtime import provider


def test_full_local_suite_and_comparison_use_no_owner_data(tmp_path):
    owner = tmp_path / "owner"
    owner.mkdir()
    marker = owner / "untouched.txt"
    marker.write_text("owner private marker", encoding="utf-8")
    report = asyncio.run(evaluate(Settings(data_dir=owner)))
    assert report.passed and report.critical_failures == 0
    assert len(report.cases) == 12
    assert {case.category for case in report.cases} >= {
        "conversation",
        "memory",
        "rag",
        "tools",
        "planning",
        "privacy",
    }
    assert "scripted-framework-probe" in report.execution
    assert "owner private marker" not in report.model_dump_json()
    assert list(owner.iterdir()) == [marker]
    assert all(value == 0 for value in compare(report, report)["score_delta"].values())
    different = report.model_copy(update={"execution": "real-model"})
    assert not compare(report, different)["comparable"]


def test_failure_report_has_classification_without_answer_echo(tmp_path, monkeypatch):
    import adam.evals.suite as suite

    async def fail(name, runtime):
        raise AssertionError("private diagnostic text never report this")

    monkeypatch.setattr(suite, "framework_case", fail)
    case = asyncio.run(execute("secret_ingress", Settings(data_dir=tmp_path)))
    assert not case.passed and case.critical
    assert case.error_code == "EVAL.RUBRIC_FAILED"
    assert "private diagnostic" not in case.model_dump_json()
    with pytest.raises(ValueError, match="UNKNOWN_SCENARIO"):
        asyncio.run(execute("not_a_scenario", Settings(data_dir=tmp_path)))


def test_replay_api_is_bounded_and_isolated(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), provider())
    password = "synthetic-replay-passphrase"
    app.state.auth.initialize(password)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/developer/evals/scenarios").status_code == 401
        client.post("/auth/login", json={"password": password})
        client.post("/auth/elevate", json={"password": password})
        assert set(client.get("/developer/evals/scenarios").json()) >= set(names())
        assert client.post("/developer/evals/replay/task_verify").json()["passed"]
        assert app.state.runtime.actions.list() == []
        assert app.state.runtime.tasks.list() == []
        assert client.post("/developer/evals/replay/not_a_scenario").status_code == 404


def test_cli_failure_exit_and_machine_report(tmp_path, monkeypatch, capsys):
    from adam.evals import runner

    async def failed(*args, **kwargs):
        case = await execute("tool_selection", Settings(data_dir=tmp_path))
        return case.model_copy(update={"passed": False, "error_code": "EVAL.RUBRIC_FAILED"})

    monkeypatch.setattr(runner, "execute", failed)
    target = tmp_path / "failed.json"
    monkeypatch.setattr(
        "sys.argv", ["adam-eval", "--replay", "tool_selection", "--output", str(target)]
    )
    with pytest.raises(SystemExit) as result:
        runner.main()
    assert result.value.code == 1
    assert json.loads(target.read_text())["error_code"] == "EVAL.RUBRIC_FAILED"
    assert json.loads(capsys.readouterr().out)["passed"] is False
