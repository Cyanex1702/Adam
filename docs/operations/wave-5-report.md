# Wave 5 implementation and QA

ADAM 0.5.0 adds typed local tools, scoped file operations, reviewed approvals,
verified action receipts, quarantine/snapshots, approved undo and persistent tasks.
The default scope is each profile's `tool-sandbox`; no user Documents access is
automatically granted. Ordinary chat remains conversational; explicit commands and
authenticated routes control effects. No additional model or GPU resources are needed.

Milestones were checkpointed sequentially: 5.0 registry (856d9a9), 5.1 permissioned
execution (3025939), 5.2 journal/undo (acd1954), 6.0 tasks (467d82a), 6.1 integrated
planning/execution/verification (3310edd), then 6.2 bounded recovery/replanning.
See the corresponding milestone notes and `gate-5.md`.

Automated QA passes **103 regression tests**, Ruff lint/format and strict mypy.
It covers actual temporary files, denied/expired/mismatched approvals,
stale previews, no-overwrite, Windows path edge cases, secret-file exclusion,
hard links, changed-file undo conflicts, snapshots/quarantine, separate Guest API
profiles, invalid dependency graphs, observe-only intent, mandatory verification,
bounded retries/replans, resource conflict, crash checkpoints, idempotence,
cancellation and reauthentication between steps. All earlier-wave tests remain
in the regression suite. Ruff lint/format and strict mypy are required.

Live QA passed **33 checks** using actual loopback HTTP and a separate ADAM terminal
process on this PC, including process restart and filesystem byte checks. Evidence:
`evidence/wave5-live-qa.json`. The live test found unclosed SQLite handles on Windows;
connections now explicitly close after transactions, with a regression test that
renames all action/task databases immediately after use. No owner data was seeded.

Core runtime schema remains 6; action/task schemas are separately versioned at 1.
Protocol remains 1.0. Existing owner authentication/vault/profile behavior is retained.
Interrupted mutations fail closed as UNCERTAIN, while completed receipts recover.
Actual application-window observation and usability are Gate 5 human checks.
No real model inference was needed for these deterministic tools; previous PC QA
already exercised Qwen and E5. This report does not claim a new model evaluation.
