# Milestone 2.2 — Long-term memory

AUTOMATED_VERIFIED, 2026-10-05. 37 tests, Ruff and strict mypy passed.

Schema 4 stores five typed owner-memory kinds, current/historical/possible temporal
state, provenance, confidence, importance, privacy, audiences, subjects, retention,
pinning, retrieval tier, and access metadata. Memory is outside model weights.
Explicit memory writes and conversation receipts commit atomically. Memory commands
work while the model server is offline. Identity accurately reports persistence.

Terminal or POST /chat commands:
- /remember [--pin] [--private] TYPE KEY = CONTENT
- Remember this: CONTENT (automatic key; explicit keys are easier to correct)
- /correct KEY_OR_ID = CONTENT
- That is wrong. (retires focused memory)
- /show memory [--history] [--archive] QUERY
- /why know KEY_OR_ID or Why do you know that? (focused record)
- /forget KEY_OR_ID or Forget that. (focused key)

TYPE: semantic, episodic, preference, project, goal. Current-key corrections retire
prior versions; uncertainty words keep POSSIBLE/UNCERTAIN records out of normal
retrieval. Repeated normalized statements merge evidence. Unknown memory queries
abstain deterministically. Learned ordinary answers remain UNCERTAIN. Explicit
memory-operation receipts are VERIFIED operations, not verification of owner claims.

GET /memory searches/inspects records; DELETE /memory/{id} invokes the same forget path.
This remains a loopback, local OS-account owner alpha; multi-user policy is Wave 4.
Filtering occurs before matching/context. Retrieved claims are data, never authority.

Forget removes all versions for the key and identifiable source/echoed transcript
turns, resets rolling summaries, and uses SQLite secure_delete. It is not forensic
secure erasure of disk sectors, external backups, or unidentifiable paraphrases.
No automatic durable extraction of ordinary chatter is enabled in this milestone.
Tests cover correction timeline, pin preservation, model-independent offline commands,
restart provenance, unknown abstention, possibilities, dedup, secret boundary, API
inspection/deletion, and memory+receipt transaction rollback.
