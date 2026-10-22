import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, ("CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",)),
    (
        2,
        (
            "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0, "
            "summary TEXT NOT NULL DEFAULT '', summary_through INTEGER NOT NULL DEFAULT 0)",
            "CREATE TABLE turns (turn_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE, "
            "user_text TEXT NOT NULL, assistant_text TEXT NOT NULL, created_at TEXT NOT NULL, "
            "trace_id TEXT NOT NULL UNIQUE, model_id TEXT NOT NULL)",
            "CREATE INDEX turns_session ON turns(session_id, turn_id)",
        ),
    ),
    (
        3,
        (
            "ALTER TABLE sessions ADD COLUMN working_state TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE sessions ADD COLUMN context_budget TEXT NOT NULL DEFAULT '{}'",
        ),
    ),
    (
        4,
        (
            "CREATE TABLE memories (memory_id TEXT PRIMARY KEY, memory_key TEXT NOT NULL, "
            "status TEXT NOT NULL, tier TEXT NOT NULL, privacy TEXT NOT NULL, "
            "record TEXT NOT NULL)",
            "CREATE INDEX memories_lookup ON memories(memory_key,status,tier)",
            "CREATE UNIQUE INDEX memory_current_key ON memories(memory_key) WHERE status='CURRENT'",
            "ALTER TABLE sessions ADD COLUMN memory_focus TEXT",
        ),
    ),
    (
        5,
        (
            "CREATE TABLE memory_candidates (candidate_id TEXT PRIMARY KEY, "
            "trace_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, record TEXT NOT NULL)",
            "ALTER TABLE sessions ADD COLUMN lease_owner TEXT",
            "ALTER TABLE sessions ADD COLUMN lease_until REAL NOT NULL DEFAULT 0",
        ),
    ),
    (
        6,
        (
            "CREATE TABLE knowledge_sources (source_id TEXT PRIMARY KEY, namespace TEXT NOT NULL, "
            "policy_key TEXT NOT NULL, content_hash TEXT NOT NULL, version INTEGER NOT NULL, "
            "status TEXT NOT NULL, record TEXT NOT NULL)",
            "CREATE INDEX knowledge_canonical ON "
            "knowledge_sources(namespace,policy_key,content_hash)",
            "CREATE TABLE knowledge_paths (path TEXT NOT NULL, namespace TEXT NOT NULL, "
            "source_id TEXT NOT NULL REFERENCES knowledge_sources(source_id), "
            "status TEXT NOT NULL, "
            "PRIMARY KEY(path,namespace))",
            "CREATE TABLE knowledge_versions (source_id TEXT NOT NULL "
            "REFERENCES knowledge_sources(source_id), "
            "version INTEGER NOT NULL, content_hash TEXT NOT NULL, parsed_text TEXT NOT NULL, "
            "record TEXT NOT NULL, PRIMARY KEY(source_id,version))",
            "CREATE TABLE knowledge_chunks (chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL "
            "REFERENCES knowledge_sources(source_id), version INTEGER NOT NULL, "
            "ordinal INTEGER NOT NULL, "
            "text TEXT NOT NULL, locator TEXT NOT NULL)",
            "CREATE INDEX knowledge_chunk_source ON knowledge_chunks(source_id,version)",
        ),
    ),
    (
        7,
        (
            "CREATE TABLE personal_links (id TEXT PRIMARY KEY, memory_id TEXT NOT NULL "
            "REFERENCES memories(memory_id) ON DELETE CASCADE, record TEXT NOT NULL)",
            "CREATE TABLE personal_goals (id TEXT PRIMARY KEY, memory_id TEXT NOT NULL "
            "REFERENCES memories(memory_id) ON DELETE CASCADE, record TEXT NOT NULL)",
            "CREATE TABLE personal_goal_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "goal_id TEXT NOT NULL REFERENCES personal_goals(id) ON DELETE CASCADE, "
            "occurred_at TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL)",
            "CREATE TABLE training_examples (id TEXT PRIMARY KEY, record TEXT NOT NULL)",
            "CREATE TABLE training_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        ),
    ),
)


def migrate(path: Path, migrations: tuple[tuple[int, tuple[str, ...]], ...] = MIGRATIONS) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, "
            "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        applied = dict(connection.execute("SELECT version, checksum FROM schema_migrations"))
        if set(applied) - {version for version, _ in migrations}:
            raise ValueError("Database schema is newer than this runtime")
        for version, statements in migrations:
            checksum = hashlib.sha256("\n".join(statements).encode()).hexdigest()
            if version in applied:
                if applied[version] != checksum:
                    raise ValueError("Applied migration checksum mismatch")
                continue
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations VALUES (?, ?, CURRENT_TIMESTAMP)",
                (version, checksum),
            )
        return max((version for version, _ in migrations), default=0)
