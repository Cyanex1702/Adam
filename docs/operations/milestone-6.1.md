# Milestone 6.1 — Planner, executor and verifier

Automated verified with 100 regression tests and static checks, 2026-10-06.
Planner validates capability metadata and dependencies before execution. Deterministic
`diagnose DIRECTORY` and `organize DIRECTORY` routes produce inspectable plans.
Structured plans support other registered tools. Ambiguous goals require clarification.
The executor creates durable action receipts; the separate verifier checks their
status and optional expected text. Fix-and-test plans require a dependent read-only
verification step. Ordinary chat cannot execute tools or grant approval.
API and terminal expose plan/preview/approve/run/cancel and action undo previews.
