# ADAM Build Wave 2 — Persistent ADAM

Implementation: AUTOMATED_VERIFIED. Human Gate 2: NOT_STARTED.
Date: 2026-10-05. Runtime/package: 0.2.0. SQLite schema: 5.

The user accepted Wave 1 and authorized Wave 2. Milestones were implemented sequentially
with independent automated checkpoints:

| Milestone | Result | Checkpoint |
|---|---|---|
| 2.0 Conversation persistence | AUTOMATED_VERIFIED; 29 tests | 83b3231 |
| 2.1 Working memory | AUTOMATED_VERIFIED; 31 tests | 2b1b7d5 |
| 2.2 Long-term memory | AUTOMATED_VERIFIED; 37 tests | 9677734 |
| 2.3 Consolidation/archive and final review | AUTOMATED_VERIFIED; 47 tests | Final Wave 2 commit |

Full successful conversation turns survive restart and model replacement, with timestamps,
trace references, transactional writes, paginated history, and explicit resumption. Working
memory keeps task/instructions outside lossy summaries, reserves output tokens, and prunes
old context before failing oversized current inputs. It never sends the whole archive.

Five owner memory types carry provenance, confidence, importance, privacy/audiences,
validity, status, pinning, retention, and access state. Deterministic remember/correct/show/
why/forget commands work offline. Corrections keep historical records. Possibilities never
become confirmed current facts. Retractions carry disputed status and retraction provenance.
Unknown lookup abstains. Owner claims are reported evidence, not independently verified.

Background consolidation requires no additional model. Narrow statement candidates need
explicit acceptance. Normalized duplicate preferences merge provenance. Source-linked
project/goal summaries preserve restrictive privacy. Decay lowers retrieval priority without
deleting facts. Low-importance unused items become COLD after 30 days. Pinned records never
auto-expire. Manual archives remain deliberately searchable; source changes invalidate
summary caches immediately. Repeating consolidation for unchanged facts/date is idempotent.

Final review added bounded idle session caching, cross-runtime renewable leases, memory
revision checks against stale commits, safe command guidance, and validated working-state
mutation. The original schema migration checksum is preserved. No new runtime dependency
or model was added. The existing Qwen3-4B-Instruct-2507 Q4_K_M Vulkan setup remains selected.

Verification completed:
- 47 unit/integration tests; Ruff lint/format; strict mypy on 24 source files.
- 17 live integration assertions against the installed model and a real API process restart.
- Real WebSocket answers: current editor "Cursor"; unknown coffee abstained; possible Linux
  switch did not become a confirmed fact. Archive/search, forgetting, and credential exclusion passed.
- All seven Wave 1 real-model smoke scenarios passed after the Wave 2 integration changes.
- Terminal start helper, working instructions/task, process restart, resume, provenance,
  quit, and lease cleanup passed. Existing user model server was reused and preserved.
- Installed package metadata upgraded to 0.2.0; default database upgraded with a pre-migration snapshot.

Live sample timings: first measured answer 37.50 seconds (37.40 to first token), then
4.61 and 4.21 seconds (3.44 and 3.46 to first token). The server was already running and
shared; the cause of the first delay was not established. Input estimates were 921/701/710
with 768 output tokens reserved within the 4096-token profile. These samples are not a
latency guarantee or a full semantic factual-accuracy evaluation.

Evidence: docs/operations/evidence/wave2-live.json, wave2-wave1-smoke.json,
wave2-terminal.json, wave2-migration.json. Tests use synthetic facts in isolated data
folders; they do not seed the user's real memory. The pre-wave migration snapshot is
under the configured local data directory's backups folder.

Known limits:
- Unicode lexical memory retrieval with narrow normalization; cross-language synonym
  discovery and semantic/vector retrieval are not implemented in this wave.
- Summaries are incomplete extracts. Critical explicit instructions are separate; full
  historical transcript remains queryable. Generated responses can still be wrong.
- Credential detection is conservative and cannot identify arbitrary unlabeled secrets.
  Never submit credentials. SQLite is local cleartext under the OS account boundary.
- Forget removes key versions and identifiable related records, not external backups,
  disk-sector remnants, or unidentifiable paraphrases.
- No remote/guest authentication, RAG, tools, voice, vision, mobile, or PC/browser control.
  Those are later waves. Candidate extraction supports narrow explicit English patterns.

Start with scripts/start.ps1. If an older terminal is open, /quit and start again.
Follow docs/operations/gate-2.md across sessions and preferably multiple days. Wave 3
has not started and awaits the user's acceptance of Gate 2.
