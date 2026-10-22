import asyncio

from adam.api.app import create_app
from adam.core.config import KnowledgeConfig, Settings
from adam.core.runtime import ChatRequest, Runtime
from adam.knowledge.contracts import SourceRequest
from adam.knowledge.grounding import GroundingService
from adam.knowledge.retrieval import QueryRequest, RetrievalService
from auth_client import OwnerClient as TestClient
from test_retrieval import TestEmbedder, make_service
from test_text_runtime import provider


def test_grounded_quotes_conflicts_and_missing_attribute(tmp_path):
    knowledge, ingest = make_service(tmp_path)
    ingest("retry.md", "retry_limit = 3\nbackoff_seconds = 2")
    ingest("revision.md", "retry_limit = 5\nbackoff_seconds = 2")
    retrieval = RetrievalService(knowledge, TestEmbedder())
    service = GroundingService(retrieval)
    try:
        answer = service.answer(QueryRequest(query="What is retry_limit?"))
        assert answer.status == "CONFLICT" and answer.epistemic_status == "RETRIEVED"
        assert answer.conflicts[0].field == "retry limit"
        assert set(answer.conflicts[0].alternatives) == {"3", "5"}
        limited = service.answer(QueryRequest(query="What is retry_limit?", limit=1))
        assert limited.status == "CONFLICT" and len(limited.citations) == 2
        for item in answer.citations:
            canonical = knowledge.chunks(item.source)
            assert any(chunk == item.chunk for chunk in canonical)
            assert item.chunk.text.replace("\r\n", "\n") in "\n".join(
                line.removeprefix("> ") for line in answer.text.splitlines()
            )
            assert item.citation in {e.citation for e in answer.retrieval.evidence}
        unknown = service.answer(QueryRequest(query="What is the retry worker salary?"))
        assert unknown.status == "ABSTAIN" and unknown.citations == []
        assert unknown.sufficiency.reason == "requested_attribute_absent"
        (tmp_path / "retry.md").unlink()
        (tmp_path / "revision.md").unlink()
        assert service.answer(QueryRequest(query="retry_limit")).status == "ABSTAIN"
    finally:
        retrieval.close()


def test_rag_receipts_do_not_become_memory_or_stale_chat_context(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        recent_turns=1,
        knowledge=KnowledgeConfig(allowed_roots=[tmp_path], embedding_dir=tmp_path / "absent"),
    )
    runtime = Runtime(settings, provider("offline"))
    path = tmp_path / "knowledge.md"
    path.write_text("My favorite editor is Orchid Studio.", encoding="utf-8")
    runtime.knowledge.ingest(SourceRequest(path=str(path)))
    try:
        event = asyncio.run(
            runtime.chat(
                ChatRequest(text="My favorite editor is what?", knowledge_namespace="default")
            )
        )
        assert event.event_type == "agent.completed", event.payload
        assert event.payload["result"]["status"] == "EVIDENCE"
        assert event.session_id
        assert runtime.store.history(event.session_id)[0]["model_id"] == "grounded_source_service"
        assert runtime.store.recent(event.session_id, 8) == []
        asyncio.run(
            runtime.chat(ChatRequest(text="/show memory editor", session_id=event.session_id))
        )
        assert "Orchid Studio" not in runtime.store.get(event.session_id)["summary"]
        runtime.consolidation.consolidate()
        assert runtime.consolidation.candidates() == []
        assert runtime.memories.search("editor") == []
        path.write_text("My favorite editor is Cedar Studio.")
        stale = asyncio.run(
            runtime.chat(ChatRequest(text="/ask favorite editor", session_id=event.session_id))
        )
        assert stale.payload["result"]["status"] == "ABSTAIN"
    finally:
        runtime.retrieval.close()


def test_knowledge_api_offline_failure_and_inspector(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        knowledge=KnowledgeConfig(allowed_roots=[tmp_path], embedding_dir=tmp_path / "absent"),
    )
    path = tmp_path / "commands.txt"
    path.write_text("Build command: cedar build\nDeployment port: 9123")
    with TestClient(
        create_app(settings, provider("offline")), base_url="http://127.0.0.1"
    ) as client:
        assert client.get("/identity").json()["capabilities"]["rag"] == "AVAILABLE_EXTRACTIVE"
        assert client.post("/knowledge/sources", json={"path": str(path)}).status_code == 200
        result = client.post("/knowledge/answer", json={"query": "Build command"}).json()
        assert result["status"] == "EVIDENCE"
        assert result["retrieval"]["mode"] == "KEYWORD"
        assert result["citations"][0]["source"]["version"] == 1
        assert client.post("/knowledge/reindex").status_code == 503
        assert (
            client.post(
                "/knowledge/retrieve", json={"query": "password=supersecret123"}
            ).status_code
            == 400
        )
        assert (
            client.post("/knowledge/answer", json={"query": "x", "audience": "owner"}).status_code
            == 422
        )
