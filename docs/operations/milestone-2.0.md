# Milestone 2.0 — Conversation persistence

AUTOMATED_VERIFIED, 2026-10-05. 29 tests, Ruff lint/format, strict mypy passed.

Schema 2 adds sessions and complete successful turns with UTC timestamps, trace IDs,
model IDs, and rolling-summary placeholders. Each turn pair and session timestamp commit
in one SQLite transaction. Failures and cancellations never become completed turns.
API lists sessions and paginates history; terminal /sessions and /resume ID restore context
across restarts. Closing a session preserves history and permits explicit resumption.

Declared secret input and recognizable credential-bearing input are rejected before
model submission. Credential-bearing model text is omitted from stored context.
Arbitrary unlabeled secrets cannot be detected reliably: never paste credentials.
Conversation SQLite is local cleartext and uses the current OS account boundary;
remote/guest authentication and a secrets vault remain later-wave work.

Tests cover runtime/model replacement, history trace links, explicit close/resume,
transaction abort rollback, and secret exclusion from database and metadata audit.
Schema 1 remains byte-for-byte unchanged in migration checksums.
