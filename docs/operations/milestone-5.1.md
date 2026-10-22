# Milestone 5.1 — Permissioned execution

Automated verified: 86 tests, Ruff lint/format and strict mypy, 2026-10-06.
Owner-only mutating previews, fresh elevated approvals bound to a digest and
five-minute expiration, precondition checks, fixed sandbox, typed results, action
IDs and no arbitrary shell execution. Guest/demo API profiles use separate roots.
Read-only calls require an explicit preview/execute but no elevation.
Registered desktop dispatch tools currently return an explicit unavailable error.
The journal marks an interrupted mutation uncertain rather than replaying it.
