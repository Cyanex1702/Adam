# Wave 7 - Resilient ADAM

Completed milestones 8.0, 8.1 and 8.2 on 2026-10-06. Source and installed runtime
are **0.7.0** at `%PROJECT_ROOT%`.
Status: `AUTOMATED_VERIFIED`; Gate 7 awaits human validation. Wave 8 has not started.
The user's Wave 7 request accepted Wave 6. Planning documents supplied requirements;
they did not authorize later waves.

Encrypted snapshots capture identity, memory, settings, journals, canonical source
blobs and sandbox data. SQLite writer reservations give a consistent boundary.
Tokens are removed from the copy; vault inclusion requires opt-in. Retention prunes
only managed archives after a new archive verifies. Busy stores, damaged archives,
wrong passphrases and unsupported schemas fail visibly.

Restore validates before publication into a fresh directory, rebinds portable
source copies and needs no original LLM. It revokes capabilities and pending
approvals instead of replaying tools. Startup faults select read-only recovery
before migrations/consolidation. Recovery inspection/export needs no model or
authentication initialization. Offline derived-index repair quarantines old data.

Human exports provide JSON, JSONL, Markdown and CSV with person, project-label,
date, conversation, task, section and memory-type filters. Provenance, timestamps,
history and candidate uncertainty survive. Credentials and denied subjects are
filtered, formula-like CSV cells are protected, and unreadable recovery sections
are marked partial. Fresh-target and size limits fail visibly.

| Validation | Result |
|---|---|
| Full regression suite | 146 passed |
| Ruff lint and format | Passed |
| Strict mypy | Passed, 61 backend source files |
| Full scripted evaluation/security gate | 22 passed, zero critical failures |
| Live HTTP and terminal maintenance QA | 37 checks passed |
| Installed Qwen3-4B and real E5 maintenance QA | 42 checks passed |
| Prior Wave 5 action/task/terminal regression | 33 checks passed |
| Installed package and application version | Both 0.7.0 |

QA used separate loopback ports and disposable synthetic PC stores. Qwen recalled
original and restored memory. E5 rebuilt and queried restored canonical sources
after the original fixture document was removed. Restore returned snapshot state
after a later correction. Recovery blocked writes/private HTTP, exported readable
sections and preserved every source file byte. QA closed its API servers and the
model process it started. No personal owner store was modified or model downloaded.

Fault tests cover archive authentication/tampering, checksum/identity mismatches,
unsafe paths/compression, retention/publication failures, writer contention, WAL
snapshots, schema drift, bad identity/settings/records, corrupt core/derived stores,
index contention, vault double opt-in, stale approvals, fresh-target refusal,
secret/policy filtering, partial salvage, export limits and CSV formulas.
One warning concerns the installed Starlette TestClient/httpx deprecation.

Checkpoint commits: milestone 8.0 `46ff086`, milestone 8.1 `39d1213`; the final
Wave 7 checkpoint contains milestone 8.2, QA and documentation. No existing schema
migration checksum or architecture contract changed.

Evidence: [live QA](evidence/wave7-live-qa.json),
[real-model QA](evidence/wave7-real-model-qa.json),
[prior-wave regression](evidence/wave5-live-qa.json),
[evaluation gate](evidence/wave7-full-eval.json).
Reproduce with `scripts/qa-wave7.py`, optionally adding `--real-model`.

Operating limits, vault recovery, filter semantics and purge scope:
[Gate 7](gate-7.md). Exports are cleartext. Models and vectors are excluded from
backups. There is no unattended scheduler or destructive purge of older copies;
restoring an older backup can reintroduce forgotten data.
