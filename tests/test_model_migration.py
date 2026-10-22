import asyncio
import json
from datetime import timedelta

import portalocker
import pytest
from adam.api.app import create_app
from adam.compute.catalog import ModelProfile
from adam.compute.contracts import ComputeError
from adam.compute.migration import ModelController, continuity
from adam.core.config import ModelConfig, Settings, load_settings
from adam.core.contracts import utc_now
from adam.core.runtime import ChatRequest, Runtime
from adam.evals.security import ATTACKS
from adam.evals.suite import CaseResult, EvalReport, ProbeProvider, names
from adam.models.base import ModelHealth
from adam.models.llama_cpp import LlamaCppProvider
from adam.resilience.recovery import inspect
from fastapi.testclient import TestClient


class ConfiguredFixture(ProbeProvider):
    def __init__(self, config, healthy=True):
        self.config = config
        self.healthy = healthy

    def get_capabilities(self):
        return LlamaCppProvider(self.config).get_capabilities()

    async def health_check(self):
        return ModelHealth(
            status="HEALTHY" if self.healthy else "DEGRADED", model_id=self.config.model_id
        )


def fixture_controller(root):
    settings = Settings(data_dir=root)
    runtime = Runtime(settings, ProbeProvider())
    controller = ModelController(runtime.compute)
    controller.factory = lambda item: ConfiguredFixture(item.model)
    controller.machine = lambda: "synthetic-machine"

    async def runner(config):
        def report(suite, cases, execution):
            return EvalReport(
                suite=suite,
                dataset_digest=suite + "-fixture-v1",
                model=LlamaCppProvider(config.model).get_capabilities().model_dump(),
                execution=execution,
                passed=True,
                critical_failures=0,
                cases=[
                    CaseResult(name=name, category="fixture", passed=True, duration_ms=10)
                    for name in cases
                ],
                scores={"fixture": 1.0},
                note="Synthetic gate-format fixture; not actual model measurements.",
            )

        return report("local-v1", names(), "real-model;real-rag"), report(
            "security-v1", ATTACKS, "adversarial-scripted-provider"
        )

    async def measure(*args):
        return {"first_token_ms": 1.0, "total_ms": 2.0, "output_chars": 4, "token_count": None}

    controller.runner, controller.measure = runner, measure
    return controller, runtime


def candidate(context=8192):
    return ModelProfile(
        profile_id="candidate",
        model=ModelConfig(
            model_id="candidate-fixture", display_name="Candidate fixture", context_limit=context
        ),
    )


def test_trial_finalize_restart_and_rollback_preserve_identity_memory(tmp_path):
    controller, runtime = fixture_controller(tmp_path)

    async def scenario():
        await runtime.chat(ChatRequest(text="/remember preference editor = SyntheticStudio"))
        before = continuity(runtime.settings)
        await controller.register(candidate())
        await controller.benchmark("current")
        report = await controller.benchmark("candidate")
        assert report["eligible"]
        result = await controller.promote("candidate", report["benchmark_id"], False)
        assert result["status"] == "TRIAL" and result["default"] == "current"
        assert runtime.provider.get_capabilities().model_id == "candidate-fixture"
        assert not (tmp_path / "config/model-selection.json").exists()
        interrupted = ModelController(Runtime(Settings(data_dir=tmp_path), ProbeProvider()).compute)
        assert interrupted.active_id == "current" and interrupted.pending_previous is None
        await controller.finalize()
        restored = load_settings(env={"ADAM_DATA_DIR": str(tmp_path)})
        assert restored.model.model_id == "candidate-fixture"
        assert continuity(runtime.settings) == before
        event = await runtime.chat(ChatRequest(text="Which editor do I prefer?"))
        assert event.event_type == "agent.completed" and "SyntheticStudio" in str(event.payload)
        # Recall legitimately updates memory access metadata; compare the swap
        # boundary separately from that intervening user turn.
        after_recall = continuity(runtime.settings)
        await controller.rollback()
        assert load_settings(env={"ADAM_DATA_DIR": str(tmp_path)}).model.model_id == "qwen3-8b"
        assert continuity(runtime.settings) == after_recall
        assert set(controller.catalog.profiles) == {"current", "candidate"}

    try:
        asyncio.run(scenario())
    finally:
        runtime.retrieval.close()


def test_missing_baseline_and_failed_or_noncomparable_gates_never_promote(tmp_path):
    controller, runtime = fixture_controller(tmp_path)

    async def scenario():
        await controller.register(candidate())
        report = await controller.benchmark("candidate")
        with pytest.raises(ComputeError, match="BASELINE_REQUIRED"):
            await controller.promote("candidate", report["benchmark_id"], False)
        await controller.benchmark("current")
        evidence = controller.evidence(report["benchmark_id"])
        evidence.local.cases[0].passed = False
        assert not controller.eligible(evidence, candidate())
        evidence.local.cases[0].passed = True
        evidence.created_at = utc_now() - timedelta(days=2)
        assert not controller.eligible(evidence, candidate())
        controller.machine = lambda: "different-machine"
        different = await controller.benchmark("candidate")
        with pytest.raises(ComputeError, match="NOT_COMPARABLE"):
            await controller.promote("candidate", different["benchmark_id"], False)
        assert controller.active_id == controller.catalog.default_id == "current"

    try:
        asyncio.run(scenario())
    finally:
        runtime.retrieval.close()


def test_reduction_requires_ack_and_failed_load_retains_previous_model(tmp_path):
    controller, runtime = fixture_controller(tmp_path)

    async def scenario():
        await controller.register(candidate(4096))
        await controller.benchmark("current")
        report = await controller.benchmark("candidate")
        with pytest.raises(ComputeError, match="ACK_REQUIRED"):
            await controller.promote("candidate", report["benchmark_id"], False)
        controller.factory = lambda item: ConfiguredFixture(item.model, healthy=False)
        with pytest.raises(ComputeError, match="CANDIDATE_UNAVAILABLE"):
            await controller.promote("candidate", report["benchmark_id"], True)
        assert controller.active_id == "current" and runtime.settings.model.model_id == "qwen3-8b"
        controller.factory = lambda item: ConfiguredFixture(item.model)
        await controller.promote("candidate", report["benchmark_id"], True)
        runtime.compute.error = "RESOURCE.OOM"
        runtime.compute.state = "ERROR"
        await controller.rollback()
        assert runtime.compute.error is None
        assert (
            controller.active_id == "current"
            and not (tmp_path / "config/model-selection.json").exists()
        )

    try:
        asyncio.run(scenario())
    finally:
        runtime.retrieval.close()


def test_altered_report_busy_operation_and_stale_controller_are_rejected(tmp_path):
    controller, runtime = fixture_controller(tmp_path)
    second = ModelController(runtime.compute)

    async def scenario():
        await controller.register(candidate())
        with pytest.raises(ComputeError, match="STALE"):
            await second.register(ModelProfile(profile_id="other", model=ModelConfig()))
        with pytest.raises(ComputeError, match="STALE"):
            await second.register(ModelProfile(profile_id="other", model=ModelConfig()))
        report = await controller.benchmark("current")
        path = tmp_path / "compute/reports" / (report["benchmark_id"] + ".json")
        data = json.loads(path.read_bytes())
        data["report"]["healthy"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ComputeError, match="CHANGED"):
            controller.evidence(report["benchmark_id"])
        with portalocker.Lock(str(tmp_path / "compute/control.lock"), mode="a+b", timeout=0):
            with pytest.raises(ComputeError, match="CONTROL_BUSY"):
                await controller.benchmark("candidate")
        async with runtime.compute.turn():
            with pytest.raises(ComputeError, match="LIFECYCLE_BUSY"):
                await controller.benchmark("candidate")

    try:
        asyncio.run(scenario())
    finally:
        runtime.retrieval.close()


def test_bad_model_selection_or_catalog_enters_read_only_recovery(tmp_path):
    settings = Settings(data_dir=tmp_path)
    runtime = Runtime(settings, ProbeProvider())
    runtime.retrieval.close()
    directory = tmp_path / "config"
    directory.mkdir()
    path = directory / "model-selection.json"
    path.write_text('{"format": 1, "model": {"base_url": "https://remote.example"}}')
    assert inspect(settings)["mode"] == "RECOVERY_READ_ONLY"
    with pytest.raises(ValueError):
        load_settings(env={"ADAM_DATA_DIR": str(tmp_path)})
    path.unlink()
    (directory / "model-catalog.json").write_text("{}")
    assert inspect(settings)["issues"] == ["MODEL.CONFIGURATION_INVALID"]


@pytest.mark.parametrize(
    "filename", ["../escape.gguf", "C:\\bad.gguf", "bad.exe", "x.gguf --shell", "a/weights.gguf"]
)
def test_owned_profile_rejects_non_basename_weights(filename):
    with pytest.raises(ValueError):
        ModelProfile(profile_id="candidate", model=ModelConfig(), managed=True, model_file=filename)


def test_model_api_does_not_accept_client_gate_claims(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), ProbeProvider())
    app.state.auth.initialize("synthetic-migration-owner-password")
    with TestClient(app, base_url="http://localhost") as client:
        client.post("/auth/login", json={"password": "synthetic-migration-owner-password"})
        assert client.get("/developer/models").status_code == 403
        client.post("/auth/elevate", json={"password": "synthetic-migration-owner-password"})
        assert (
            client.post("/developer/models", json=candidate().model_dump(mode="json")).status_code
            == 200
        )
        result = client.post(
            "/developer/models/candidate/promote", json={"benchmark_id": "forged", "passed": True}
        )
        assert result.status_code == 422 and "forged" not in result.text
        assert (
            client.post(
                "/developer/models/candidate/promote", json={"benchmark_id": "forged"}
            ).json()["error"]
            == "MODEL.BENCHMARK_NOT_FOUND"
        )


def test_interrupted_finalize_keeps_saved_selection_authoritative(tmp_path, monkeypatch):
    import adam.compute.migration as migration

    controller, runtime = fixture_controller(tmp_path)

    async def scenario():
        await controller.register(candidate())
        await controller.benchmark("current")
        report = await controller.benchmark("candidate")
        await controller.promote("candidate", report["benchmark_id"], False)
        original = migration.publish

        def interrupted(root, relative, value):
            if relative == "config/model-selection.json":
                raise ComputeError("MODEL.METADATA_IO_FAILED")
            original(root, relative, value)

        monkeypatch.setattr(migration, "publish", interrupted)
        with pytest.raises(ComputeError, match="METADATA_IO_FAILED"):
            await controller.finalize()
        fresh_settings = load_settings(env={"ADAM_DATA_DIR": str(tmp_path)})
        fresh_runtime = Runtime(fresh_settings, ProbeProvider())
        try:
            restarted = ModelController(fresh_runtime.compute)
            assert restarted.active_id == restarted.catalog.default_id == "current"
        finally:
            fresh_runtime.retrieval.close()
        assert controller.pending_previous == "current"

    try:
        asyncio.run(scenario())
    finally:
        runtime.retrieval.close()


def test_conflicting_model_configuration_enters_recovery(tmp_path):
    controller, runtime = fixture_controller(tmp_path)
    try:
        asyncio.run(controller.register(candidate()))
        settings = Settings(data_dir=tmp_path, model=ModelConfig(model_id="unregistered"))
        assert inspect(settings)["issues"] == ["MODEL.CONFIGURATION_INVALID"]
    finally:
        runtime.retrieval.close()


def test_failed_benchmark_restore_latches_visible_error(tmp_path, monkeypatch):
    from adam.compute.owned import OwnedLlamaProvider

    controller, runtime = fixture_controller(tmp_path)
    previous = OwnedLlamaProvider(
        ModelProfile(
            profile_id="current",
            model=runtime.settings.model,
            managed=True,
            model_file="fixture.gguf",
        )
    )
    previous.process = object()

    async def unload():
        previous.process = None

    async def load():
        raise OSError("synthetic private path")

    monkeypatch.setattr(previous, "unload", unload)
    monkeypatch.setattr(previous, "load", load)
    controller.manager.delegate = previous
    try:
        with pytest.raises(ComputeError, match="MODEL.RESTORE_FAILED"):
            asyncio.run(controller.benchmark("current"))
        assert controller.manager.error == "MODEL.RESTORE_FAILED"
        assert controller.manager.state == "ERROR"
        assert controller.active_id == "current"
    finally:
        runtime.retrieval.close()


def test_existing_guest_context_follows_shared_model_swap(tmp_path):
    from adam.security.policy import Principal

    controller, owner_runtime = fixture_controller(tmp_path)
    guest = Runtime(
        owner_runtime.settings,
        owner_runtime.compute,
        Principal(
            mode="guest",
            person_id="guest",
            authenticated=False,
            elevated=False,
            profile_id="fixture",
        ),
    )

    async def scenario():
        selected = candidate()
        selected.model.max_tokens = 256
        await controller.register(selected)
        await controller.benchmark("current")
        report = await controller.benchmark("candidate")
        await controller.promote("candidate", report["benchmark_id"], False)
        event = await guest.chat(ChatRequest(text="What are you?"))
        assert event.event_type == "agent.completed"
        assert guest.context.reserve == 256
        assert guest.context.limit == selected.model.context_limit
        assert guest.settings.data_dir != owner_runtime.settings.data_dir

    try:
        asyncio.run(scenario())
    finally:
        guest.retrieval.close()
        owner_runtime.retrieval.close()
