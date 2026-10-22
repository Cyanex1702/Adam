# ADR 0005 — Transactional local memory and bounded context

Accepted for Wave 2, 2026-10-05.

SQLite remains the canonical conversation and personal-memory store. Successful turn
pairs, memory mutations, and their conversation receipts commit atomically. Session
leases coordinate terminal/API runtimes and expire after 60 seconds, with renewal
every 20 seconds. An idle bounded cache never replaces the persisted archive.

The context builder separates identity, owner task/instructions, recent turns, extractive
working summary, and retrieved current memory. It reserves output, removes older turn
pairs under pressure, then removes summary/retrieval blocks. It never truncates the
current input or explicit owner instruction block. Provider token counting remains
replaceable, with the existing conservative fallback. Raw transcripts are never loaded
wholesale into model context. Summaries are lossy, labelled excerpts, not fact creation.

Memory is controlled by deterministic owner commands. No model output can claim a
successful memory write. Five memory types share provenance, privacy/audience metadata,
temporal state, confidence, pinning, and retention fields. Reported statements remain
reported. Possibilities are excluded from current-fact retrieval. Explicit corrections
retire old values; retractions retain disputed history. Unknown lookup abstains.

Search is a Unicode lexical matcher with narrow normalization (including VS Code/vscode).
It filters the local owner's scope before matching and context. It is not semantic/vector
retrieval or a guarantee of cross-language synonym discovery; RAG remains Wave 3.
No remote or guest requester exists in this alpha. The local OS account is the current
owner boundary; authentication/policy-engine enforcement remains Wave 4.

Background consolidation uses no model, scans bounded batches for narrow explicit
statement candidates, deduplicates supported normalized statements, computes retrieval
priority decay, and creates source-linked project/goal summary caches. Candidate acceptance
is explicit; background work never promotes a suggestion into confirmed memory. Pinned
records never auto-expire. Low-importance items unused for 30 days move to COLD;
meaningful records stay searchable and are not deleted. Source changes invalidate derived
summaries immediately. Consolidation is idempotent for unchanged facts and UTC date.

Forget removes a key's versions, matching candidates, identifiable source/echoed turns,
related working fields, and derived summaries. SQLite secure_delete is enabled. Memory
revision checks prevent committing an answer generated against changed memory. This
is application forgetting, not forensic disk erasure or external-backup management.

Declared secrets and recognizable credentials are rejected before model submission.
Credential-bearing generated text is omitted from persisted context. Detection is
conservative and cannot infer arbitrary unlabeled secrets; never submit credentials.
The database is local cleartext. Audit traces contain operational metadata only. A
prepared trace is mandatory before committing a turn; terminal telemetry is best effort.
