# Milestone 6.2 — Bounded recovery and replanning

Automated verified: 103 regressions, Ruff lint/format, strict mypy and 33 real
loopback API/terminal checks on this PC, 2026-10-06.

Action and task resource locks serialize competing processes. Completed effects
are reused by stable per-step idempotency keys after restart. Crash after an action
receipt but before the task checkpoint does not duplicate the effect. Interrupted
mutations stay UNCERTAIN and cannot be replayed/replanned into an assumed success.
Read-only retries are capped at two retries; replacements at two replans, each
requiring a new approval. Time usage persists. Cancellation cannot be overwritten
by an in-flight checkpoint. Authority is rechecked between API task steps. Expired
approvals and changed resources stop execution. SQLite handles explicitly close.
