import hashlib
import os
from collections.abc import Callable
from pathlib import Path

from adam.core.config import KnowledgeConfig
from adam.core.contracts import new_id, utc_now
from adam.core.privacy import contains_secret
from adam.core.storage import ConversationStore
from adam.knowledge.contracts import Chunk, SourceRecord, SourceRequest
from adam.knowledge.parsing import IngestionError, LineChunker, parse


class KnowledgeService:
    def __init__(self, store: ConversationStore, config: KnowledgeConfig) -> None:
        self.store = store
        self.config = config
        self.blobs = store.path.parent / "knowledge" / "blobs"
        self.chunker = LineChunker(config.chunk_chars)

    def safe_path(self, path: str) -> Path:
        candidate = Path(path).expanduser().resolve()
        if not any(
            candidate.is_relative_to(root.expanduser().resolve())
            for root in self.config.allowed_roots
        ):
            raise IngestionError("Source is outside configured knowledge.allowed_roots.")
        return candidate

    def sources(self, namespace: str | None = None) -> list[SourceRecord]:
        with self.store.connect() as db:
            return [
                SourceRecord.model_validate_json(row[0])
                for row in db.execute(
                    "SELECT record FROM knowledge_sources WHERE (? IS NULL OR namespace=?)",
                    (namespace, namespace),
                )
            ]

    def chunks(self, source: SourceRecord) -> list[Chunk]:
        with self.store.connect() as db:
            return [
                Chunk.model_validate(dict(row))
                for row in db.execute(
                    "SELECT * FROM knowledge_chunks WHERE source_id=? "
                    "AND version=? ORDER BY ordinal",
                    (source.source_id, source.version),
                )
                if not contains_secret(row["text"])
            ]

    def snapshot(
        self, namespace: str | None, allowed: Callable[[SourceRecord], bool]
    ) -> tuple[list[SourceRecord], list[tuple[SourceRecord, Chunk]], int]:
        """One consistent canonical read, including policy, versions and revision."""
        with self.store.connect() as db:
            db.execute("BEGIN")
            sources = [
                SourceRecord.model_validate_json(row[0])
                for row in db.execute(
                    "SELECT record FROM knowledge_sources WHERE (? IS NULL OR namespace=?)",
                    (namespace, namespace),
                )
            ]
            pairs = [
                (source, Chunk.model_validate(dict(row)))
                for source in sources
                if allowed(source)
                for row in db.execute(
                    "SELECT * FROM knowledge_chunks WHERE source_id=? "
                    "AND version=? ORDER BY ordinal",
                    (source.source_id, source.version),
                )
                if not contains_secret(row["text"])
            ]
            row = db.execute(
                "SELECT value FROM runtime_metadata WHERE key='knowledge_revision'"
            ).fetchone()
            return sources, pairs, int(row[0]) if row else 0

    def ingest(self, request: SourceRequest) -> SourceRecord:
        path = self.safe_path(request.path)
        if request.policy.sensitivity in {"SECRET", "SYSTEM_SECRET", "NEVER_LLM", "NEVER_LOG"}:
            raise IngestionError("Secrets/never-LLM sources cannot be ingested.")
        try:
            if not path.is_file() or path.stat().st_size > self.config.max_file_bytes:
                raise IngestionError("Source is missing, not a file, or exceeds the size limit.")
            raw = path.read_bytes()
        except OSError:
            raise IngestionError("Source could not be read.") from None
        if len(raw) > self.config.max_file_bytes:
            raise IngestionError("Source exceeds size limit.")
        if contains_secret(raw.decode("utf-8", errors="ignore")):
            raise IngestionError("Credential-bearing sources are rejected before parsing/storage.")
        media_type, blocks = parse(path, raw)
        text = "\n".join(block.text for block in blocks)
        if not text.strip() or len(text) > 1_000_000:
            raise IngestionError(
                "No extractable text or too much text. Scanned PDFs require OCR elsewhere."
            )
        if contains_secret(text) or contains_secret(raw.decode("utf-8", errors="ignore")):
            raise IngestionError("Credential-bearing sources are rejected before storage/indexing.")
        digest = hashlib.sha256(raw).hexdigest()
        # Keep legacy owner policy hashes stable; other profiles have separate identities.
        policy_json = request.policy.model_dump_json(
            exclude={"profile"} if request.policy.profile == "owner" else set()
        )
        policy_key = hashlib.sha256(policy_json.encode()).hexdigest()
        self.blobs.mkdir(parents=True, exist_ok=True)
        target = self.blobs / (digest + ".bin")
        if not target.exists():
            temporary = self.blobs / (digest + "." + new_id() + ".part")
            temporary.write_bytes(raw)
            os.replace(temporary, target)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT record FROM knowledge_sources WHERE namespace=? AND "
                "policy_key=? AND content_hash=?",
                (request.namespace, policy_key, digest),
            ).fetchone()
            prior = db.execute(
                "SELECT s.record FROM knowledge_paths p JOIN knowledge_sources s "
                "ON p.source_id=s.source_id WHERE p.path=? AND p.namespace=?",
                (str(path), request.namespace),
            ).fetchone()
            old = SourceRecord.model_validate_json(prior[0]) if prior else None
            if existing:
                source = SourceRecord.model_validate_json(existing[0])
                source.path, source.title, source.status = str(path), path.name, "ACTIVE"
            else:
                aliases = db.execute(
                    "SELECT COUNT(*) FROM knowledge_paths WHERE source_id=? AND status='ACTIVE'",
                    (old.source_id if old else "",),
                ).fetchone()[0]
                same_policy = old and old.policy == request.policy
                source = SourceRecord(
                    source_id=old.source_id if old and aliases <= 1 and same_policy else new_id(),
                    namespace=request.namespace,
                    title=path.name,
                    path=str(path),
                    media_type=media_type,
                    content_hash=digest,
                    version=old.version + 1 if old and aliases <= 1 and same_policy else 1,
                    policy=request.policy,
                    ingested_at=utc_now(),
                )
            db.execute(
                "INSERT INTO knowledge_sources VALUES (?,?,?,?,?,?,?) ON CONFLICT(source_id) "
                "DO UPDATE SET content_hash=excluded.content_hash,version=excluded.version,"
                "status=excluded.status,record=excluded.record",
                (
                    source.source_id,
                    source.namespace,
                    policy_key,
                    digest,
                    source.version,
                    source.status,
                    source.model_dump_json(),
                ),
            )
            db.execute(
                "INSERT INTO knowledge_paths VALUES (?,?,?,'ACTIVE') ON CONFLICT(path,namespace) "
                "DO UPDATE SET source_id=excluded.source_id,status='ACTIVE'",
                (str(path), request.namespace, source.source_id),
            )
            db.execute(
                "INSERT OR IGNORE INTO knowledge_versions VALUES (?,?,?,?,?)",
                (source.source_id, source.version, digest, text, source.model_dump_json()),
            )
            for chunk in self.chunker.chunks(source.source_id, source.version, blocks):
                db.execute(
                    "INSERT OR IGNORE INTO knowledge_chunks VALUES (?,?,?,?,?,?)",
                    (
                        chunk.chunk_id,
                        chunk.source_id,
                        chunk.version,
                        chunk.ordinal,
                        chunk.text,
                        chunk.locator,
                    ),
                )
            db.execute(
                "INSERT INTO runtime_metadata VALUES ('knowledge_revision','1') ON CONFLICT(key) "
                "DO UPDATE SET value=CAST(value AS INTEGER)+1"
            )
        self.refresh(request.namespace)
        return next(
            item for item in self.sources(request.namespace) if item.source_id == source.source_id
        )

    def refresh(self, namespace: str | None = None) -> list[SourceRecord]:
        """Mark freshness before retrieval; reingest explicitly to update changed content."""
        with self.store.connect() as db:
            for source in self.sources(namespace):
                paths = db.execute(
                    "SELECT path FROM knowledge_paths WHERE source_id=?", (source.source_id,)
                ).fetchall()
                statuses = []
                for row in paths:
                    try:
                        path = self.safe_path(row[0])
                        status = (
                            "MISSING"
                            if not path.is_file()
                            else (
                                "ACTIVE"
                                if path.stat().st_size <= self.config.max_file_bytes
                                and hashlib.sha256(path.read_bytes()).hexdigest()
                                == source.content_hash
                                else "STALE"
                            )
                        )
                    except (OSError, IngestionError):
                        status = "BLOCKED"
                    db.execute(
                        "UPDATE knowledge_paths SET status=? WHERE path=? AND source_id=?",
                        (status, row[0], source.source_id),
                    )
                    statuses.append((status, row[0]))
                active = next((path for status, path in statuses if status == "ACTIVE"), None)
                new_status = (
                    "ACTIVE"
                    if active
                    else (
                        "STALE" if any(status == "STALE" for status, _ in statuses) else "MISSING"
                    )
                )
                if source.status != new_status or (active and source.path != active):
                    source.status = new_status  # type: ignore[assignment]
                    if active:
                        source.path, source.title = active, Path(active).name
                    db.execute(
                        "UPDATE knowledge_sources SET status=?,record=? WHERE source_id=?",
                        (source.status, source.model_dump_json(), source.source_id),
                    )
                    db.execute(
                        "INSERT INTO runtime_metadata VALUES ('knowledge_revision','1') "
                        "ON CONFLICT(key) "
                        "DO UPDATE SET value=CAST(value AS INTEGER)+1"
                    )
        return self.sources(namespace)
