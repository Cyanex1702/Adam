import asyncio

from adam.core.config import Settings
from adam.core.contracts import TraceId, new_id
from adam.core.runtime import ChatRequest, Runtime
from adam.core.working import WorkingState
from adam.memory.service import MemoryService
from adam.security.policy import Principal, ResourcePolicy, decide
from test_text_runtime import provider


def test_policy_denials_and_disclosure_controller():
    resource = ResourcePolicy(
        sensitivity="PRIVATE",
        allowed_audiences=["owner", "guest"],
        subjects=["owner"],
        disclosure_owner="owner",
        source_actor="owner",
    )
    assert decide(Principal(), resource).allowed
    assert (
        decide(Principal("guest", "guest", False, False), resource).reason
        == "POLICY.PROFILE_MISMATCH"
    )
    assert (
        decide(Principal(authenticated=False), resource).reason == "POLICY.AUTHENTICATION_REQUIRED"
    )
    assert (
        decide(Principal(), resource.model_copy(update={"disclosure_owner": "friend"})).reason
        == "POLICY.DISCLOSURE_OWNER_DENIED"
    )
    assert (
        decide(Principal(), resource.model_copy(update={"sensitivity": "NEVER_LLM"})).reason
        == "POLICY.SECRET_NEVER_LLM"
    )


def test_guest_context_filters_before_matching_or_prompt(tmp_path):
    runtime = Runtime(Settings(data_dir=tmp_path), provider("offline"))
    asyncio.run(
        runtime.chat(
            ChatRequest(text="/remember --private semantic project = hidden-cobalt-owner-project")
        )
    )
    guest = MemoryService(runtime.store, Principal("guest", "guest", False, False))
    assert guest.search("project") == []
    assert "hidden-cobalt" not in guest.context("project")
    assert "hidden-cobalt" in runtime.memories.context("project")
    messages, _ = asyncio.run(
        runtime.context.build(
            runtime.system_prompt(),
            WorkingState(),
            "",
            [],
            "Tell me about the project",
            TraceId(new_id()),
            memories=guest.context("project"),
        )
    )
    assert all("hidden-cobalt" not in message.content for message in messages)


def test_legacy_owner_policy_hash_preserves_source_identity(tmp_path):
    import json

    from adam.core.config import KnowledgeConfig
    from adam.knowledge.contracts import SourceRequest
    from adam.knowledge.service import KnowledgeService

    knowledge = KnowledgeService(
        Runtime(Settings(data_dir=tmp_path / "data"), provider()).store,
        KnowledgeConfig(allowed_roots=[tmp_path]),
    )
    first = tmp_path / "original.txt"
    first.write_text("A legacy source with stable identity.")
    source = knowledge.ingest(SourceRequest(path=str(first)))
    legacy = json.loads(source.model_dump_json())
    legacy["policy"].pop("profile")
    with knowledge.store.connect() as db:
        db.execute(
            "UPDATE knowledge_sources SET record=? WHERE source_id=?",
            (json.dumps(legacy), source.source_id),
        )
    duplicate = tmp_path / "duplicate.txt"
    duplicate.write_bytes(first.read_bytes())
    assert knowledge.ingest(SourceRequest(path=str(duplicate))).source_id == source.source_id
