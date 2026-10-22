import hashlib
import json
import math
import re
import sqlite3
import threading
from collections import Counter

from pydantic import Field
from qdrant_client import QdrantClient, models

from adam.core.contracts import Contract
from adam.core.privacy import contains_secret
from adam.knowledge.contracts import Chunk, SourceRecord
from adam.knowledge.embedding import Embedder, EmbeddingUnavailable, LocalE5
from adam.knowledge.service import KnowledgeService
from adam.security.policy import Principal, ResourcePolicy, decide


class QueryRequest(Contract):
    query: str = Field(min_length=1, max_length=2000)
    namespace: str = Field(default="default", pattern=r"^[\w-]{1,64}$")
    limit: int = Field(default=5, ge=1, le=10)


class Evidence(Contract):
    citation: str
    chunk: Chunk
    source: SourceRecord
    keyword_score: float = 0
    semantic_score: float | None = None
    rank_score: float = 0


class RetrievalResult(Contract):
    namespace: str
    evidence: list[Evidence]
    mode: str
    diagnostic: str | None = None
    revision: int
    excluded_stale: int = 0
    context: str = ""


def terms(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def authorized(source: SourceRecord, principal: Principal | None = None) -> bool:
    policy = source.policy
    return (
        source.status == "ACTIVE"
        and decide(
            principal or Principal(),
            ResourcePolicy(
                replication_policy=policy.replication_policy,
                sensitivity=policy.sensitivity,
                allowed_audiences=policy.allowed_audiences,
                subjects=policy.subjects,
                disclosure_owner=policy.disclosure_owner,
                source_actor=policy.source_actor,
                profile=policy.profile,
            ),
        ).allowed
    )


class RetrievalService:
    def __init__(
        self,
        knowledge: KnowledgeService,
        embedder: Embedder | None = None,
        principal: Principal | None = None,
    ) -> None:
        self.knowledge = knowledge
        self.principal = principal or Principal()
        self.embedder = embedder or LocalE5(
            knowledge.config.embedding_dir, knowledge.config.embedding_threads
        )
        self._client: QdrantClient | None = None
        self._lock = threading.RLock()
        identity = f"{self.embedder.model_id}:{self.embedder.dimensions}"
        self._collection = "adam_knowledge_" + hashlib.sha256(identity.encode()).hexdigest()[:12]
        self._receipt = knowledge.store.path.parent / "knowledge" / "index-receipt.json"

    def revision(self) -> int:
        with self.knowledge.store.connect() as db:
            row = db.execute(
                "SELECT value FROM runtime_metadata WHERE key='knowledge_revision'"
            ).fetchone()
            return int(row[0]) if row else 0

    def _open(self) -> QdrantClient:
        if self._client is None:
            try:
                self._client = QdrantClient(path=str(self._receipt.parent / "vectors"))
            except (RuntimeError, OSError, ValueError, sqlite3.Error):
                raise EmbeddingUnavailable("Local vector index is busy/unavailable.") from None
        return self._client

    def _ensure_index(self, rebuild: bool = False) -> int:
        _, pairs, revision = self.knowledge.snapshot(None, self.allowed)
        chunks = [chunk for _, chunk in pairs]
        expected = {
            "revision": revision,
            "model": self.embedder.model_id,
            "dimensions": self.embedder.dimensions,
        }
        client = self._open()
        exists = client.collection_exists(self._collection)
        if not rebuild and exists and self._receipt.is_file():
            try:
                if json.loads(self._receipt.read_text(encoding="utf-8")) == expected:
                    return len(chunks)
            except (ValueError, OSError):
                pass
        # Embedding only authorized current chunks, before writing any index receipt.
        vectors = self.embedder.documents([chunk.text for chunk in chunks]) if chunks else []
        if len(vectors) != len(chunks):
            raise EmbeddingUnavailable("Embedding provider returned incomplete vectors.")
        if exists:
            # Public point deletion keeps collection handles owned until close. Qdrant's
            # local delete_collection leaves SQLite handles open on Windows in 1.19.1.
            client.delete(
                self._collection, points_selector=models.FilterSelector(filter=models.Filter())
            )
        else:
            client.create_collection(
                self._collection,
                vectors_config=models.VectorParams(
                    size=self.embedder.dimensions, distance=models.Distance.COSINE
                ),
            )
        for offset in range(0, len(chunks), 64):
            client.upsert(
                self._collection,
                points=[
                    models.PointStruct(
                        id=chunk.chunk_id,
                        vector=vector,
                        payload={"source_id": chunk.source_id, "version": chunk.version},
                    )
                    for chunk, vector in zip(
                        chunks[offset : offset + 64], vectors[offset : offset + 64], strict=True
                    )
                ],
            )
        if revision != self.revision():
            raise EmbeddingUnavailable("Sources changed while indexing; retry.")
        self._receipt.write_text(json.dumps(expected), encoding="utf-8")
        return len(chunks)

    def reindex(self) -> dict[str, object]:
        with self._lock:
            if not self.knowledge.config.enabled:
                raise EmbeddingUnavailable("Knowledge retrieval is disabled.")
            self.knowledge.refresh()
            return {
                "chunks": self._ensure_index(True),
                "model": self.embedder.model_id,
                "canonical_sources_retained": True,
            }

    def search(self, request: QueryRequest) -> RetrievalResult:
        if contains_secret(request.query):
            raise ValueError("Credential-bearing queries are rejected.")
        with self._lock:
            if not self.knowledge.config.enabled:
                return RetrievalResult(
                    namespace=request.namespace,
                    evidence=[],
                    mode="DISABLED",
                    revision=self.revision(),
                )
            self.knowledge.refresh()
            sources, pairs, revision = self.knowledge.snapshot(request.namespace, self.allowed)
            query_terms = set(terms(request.query))
            documents = [Counter(terms(chunk.text)) for _, chunk in pairs]
            frequencies = Counter(term for document in documents for term in document)
            average = sum(sum(document.values()) for document in documents) / max(1, len(documents))
            keyword: dict[str, float] = {}
            for (_, chunk), counts in zip(pairs, documents, strict=True):
                score = 0.0
                for term in query_terms & counts.keys():
                    inverse = math.log(
                        1 + (len(documents) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)
                    )
                    frequency = counts[term]
                    score += (
                        inverse
                        * frequency
                        * 2.2
                        / (frequency + 1.2 * (0.25 + 0.75 * sum(counts.values()) / max(1, average)))
                    )
                if score:
                    keyword[chunk.chunk_id] = score
            dense: dict[str, float] = {}
            diagnostic = None
            if pairs:
                try:
                    self._ensure_index()
                    response = self._open().query_points(
                        self._collection,
                        query=self.embedder.query(request.query),
                        query_filter=models.Filter(
                            must=[
                                models.HasIdCondition(has_id=[chunk.chunk_id for _, chunk in pairs])
                            ]
                        ),
                        limit=min(50, len(pairs)),
                        with_payload=False,
                    )
                    dense = {str(point.id): point.score for point in response.points}
                except (EmbeddingUnavailable, OSError, RuntimeError, ValueError):
                    diagnostic = (
                        "RAG.VECTOR_UNAVAILABLE: keyword retrieval remains available; "
                        "check model/index setup."
                    )
            combined: dict[str, float] = {}
            for ranking in [keyword, dense]:
                for rank, chunk_id in enumerate(
                    sorted(ranking, key=lambda item: (-ranking[item], item)), 1
                ):
                    combined[chunk_id] = combined.get(chunk_id, 0) + 1 / (60 + rank)
            ranked = sorted(
                pairs, key=lambda pair: (-combined.get(pair[1].chunk_id, 0), pair[1].chunk_id)
            )
            evidence = [
                Evidence(
                    citation=f"S{index}",
                    chunk=chunk,
                    source=source,
                    keyword_score=keyword.get(chunk.chunk_id, 0),
                    semantic_score=dense.get(chunk.chunk_id),
                    rank_score=combined[chunk.chunk_id],
                )
                for index, (source, chunk) in enumerate(
                    [pair for pair in ranked if pair[1].chunk_id in combined][: request.limit], 1
                )
            ]
            # JSON is evidence data, never instructions; chunk/limit contracts bound its size.
            context = json.dumps(
                [
                    {
                        "citation": item.citation,
                        "text": item.chunk.text,
                        "locator": item.chunk.locator,
                        "source_id": item.source.source_id,
                        "version": item.source.version,
                        "trust": item.source.policy.trust,
                    }
                    for item in evidence
                ],
                ensure_ascii=False,
            )
            if revision != self.revision():
                raise ValueError("Knowledge changed during retrieval; retry.")
            return RetrievalResult(
                namespace=request.namespace,
                evidence=evidence,
                mode="HYBRID" if dense else "KEYWORD",
                diagnostic=diagnostic,
                revision=revision,
                excluded_stale=sum(source.status != "ACTIVE" for source in sources),
                context=context,
            )

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None
            if isinstance(self.embedder, LocalE5):
                self.embedder.close()

    def allowed(self, source: SourceRecord) -> bool:
        return authorized(source, self.principal)
