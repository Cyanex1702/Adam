from pathlib import Path

import pytest
from adam.core.config import KnowledgeConfig
from adam.core.storage import ConversationStore
from adam.knowledge.contracts import SourcePolicy, SourceRequest
from adam.knowledge.embedding import EmbeddingUnavailable
from adam.knowledge.retrieval import QueryRequest, RetrievalService
from adam.knowledge.service import KnowledgeService


class TestEmbedder:
    __test__ = False
    model_id = "test-only"
    dimensions = 3

    def __init__(self):
        self.seen = []

    def documents(self, texts):
        self.seen.extend(texts)
        return [[1.0, 0.0, 0.0] for _ in texts]

    def query(self, text):
        return [1.0, 0.0, 0.0]


def make_service(tmp_path: Path):
    knowledge = KnowledgeService(
        ConversationStore(tmp_path / "data" / "runtime.sqlite3"),
        KnowledgeConfig(allowed_roots=[tmp_path], embedding_dir=tmp_path / "absent"),
    )

    def ingest(name, text, namespace="default", policy=None):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return knowledge.ingest(
            SourceRequest(path=str(path), namespace=namespace, policy=policy or SourcePolicy())
        )

    return knowledge, ingest


def test_qdrant_scope_freshness_rebuild_and_restart(tmp_path):
    knowledge, ingest = make_service(tmp_path)
    accepted = ingest("build.md", "The build command is hatch build.")
    ingest(
        "blocked.md",
        "Forbidden phrase azure elephant.",
        policy=SourcePolicy(allowed_audiences=["guest"]),
    )
    ingest("other.md", "Other project uses meson build.", namespace="other")
    model = TestEmbedder()
    retrieval = RetrievalService(knowledge, model)
    try:
        result = retrieval.search(QueryRequest(query="build command"))
        assert result.mode == "HYBRID"
        assert all(item.source.source_id == accepted.source_id for item in result.evidence)
        assert not any("Forbidden" in text for text in model.seen)
        assert result.evidence[0].chunk.locator.startswith("lines:")
        assert retrieval.reindex()["canonical_sources_retained"]
    finally:
        retrieval.close()
    restarted = RetrievalService(knowledge, model)
    try:
        assert restarted.search(QueryRequest(query="hatch")).evidence
        (tmp_path / "build.md").write_text("The build command is uv build.")
        assert not restarted.search(QueryRequest(query="hatch")).evidence
        assert knowledge.sources("default")[0].status == "STALE"
        ingest("build.md", "The build command is uv build.")
        updated = restarted.search(QueryRequest(query="uv build"))
        assert updated.evidence[0].source.version == 2
        assert "hatch" not in updated.context
        assert knowledge.blobs.exists()
    finally:
        restarted.close()
    # A real Windows directory rename detects lingering local-index file handles.
    vectors = knowledge.store.path.parent / "knowledge" / "vectors"
    vectors.rename(vectors.with_name("closed-vectors"))


def test_disabled_retrieval_never_embeds(tmp_path):
    knowledge, ingest = make_service(tmp_path)
    ingest("notes.txt", "Current build uses cedar.")
    knowledge.config.enabled = False
    model = TestEmbedder()
    retrieval = RetrievalService(knowledge, model)
    try:
        result = retrieval.search(QueryRequest(query="build"))
        assert result.mode == "DISABLED" and result.evidence == []
        assert model.seen == []
    finally:
        retrieval.close()


def test_concurrent_source_mutation_rejects_old_evidence(tmp_path):
    knowledge, ingest = make_service(tmp_path)
    ingest("notes.txt", "The current port is 9123.")

    class MutatingEmbedder(TestEmbedder):
        def documents(self, texts):
            vectors = super().documents(texts)
            ingest("notes.txt", "The current port is 9444.")
            return vectors

    retrieval = RetrievalService(knowledge, MutatingEmbedder())
    try:
        with pytest.raises(ValueError, match="changed"):
            retrieval.search(QueryRequest(query="current port"))
    finally:
        retrieval.close()


def test_embedding_failure_keyword_fallback_and_query_privacy(tmp_path):
    knowledge, ingest = make_service(tmp_path)
    ingest("notes.txt", "Orchid release uses port 9123.")
    retrieval = RetrievalService(knowledge)
    try:
        result = retrieval.search(QueryRequest(query="Orchid port"))
        assert result.mode == "KEYWORD" and result.diagnostic
        assert result.evidence[0].chunk.text == "Orchid release uses port 9123."
        with pytest.raises(EmbeddingUnavailable):
            retrieval.reindex()
        with pytest.raises(ValueError):
            retrieval.search(QueryRequest(query="password=supersecret123"))
    finally:
        retrieval.close()
