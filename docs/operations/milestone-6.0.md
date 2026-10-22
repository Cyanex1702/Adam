# Milestone 6.0 — Persistent structured tasks

Automated verification: 93 regression tests and all static checks, 2026-10-06.
Tasks use a separate version-1 SQLite store. Plans contain bounded ordered DAGs,
explicit dependencies, priorities, objectives, typed calls, expected results,
retry/time limits, checkpoints and cancellation. Restart reuses action idempotency
keys and completed receipts. Plan approvals bind the graph and initial filesystem
preconditions; stale plans cannot begin execution. Guest/demo cannot create tasks.
