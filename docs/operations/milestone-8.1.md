# Milestone 8.1 - Restore and Recovery Mode

Verification: 132 tests, Ruff lint/format, strict mypy and 22 evaluation/security
cases pass. Restore validates before writing, stages under the explicitly chosen
parent and publishes only into a destination that does not exist. The original
store is never replaced. Restored identity, memories, provenance, settings, source
blobs, receipts and empty sandbox directories are retained. Active data paths are
rebound; canonical source copies let retrieval work without original external files.

Sessions, leases and pending action/task approvals are revoked. Pending actions
become UNCERTAIN; unfinished tasks pause for review. Historical receipts remain
reported evidence, not a fresh verification of effects on this installation.
The vault requires explicit inclusion AND explicit restore, retaining its original
vault password/DPAPI protection. Cross-account DPAPI cannot be unlocked automatically.
Models and derived indexes are excluded. Keyword retrieval works without E5;
explicit offline rebuild uses installed E5 and needs no original LLM.

Corrupt stores, schema drift, invalid records, identity and saved settings enter
RECOVERY_READ_ONLY before initialization. The API exposes safe health only;
local OS-trusted maintenance CLI supports inspection and isolated restore without
migration, consolidation or model calls. Unresolved WAL requires stopping writers
before immutable inspection; no WAL sidecar is deleted or ignored silently.

Offline index repair refuses an active Qdrant lock, preserves old vectors/receipt
in a quarantine directory and rebuilds from canonical data. Tests cover no-model
restore, unchanged source hashes, stale permissions, vault opt-in, fresh-target
refusal, publication failure, corruption, schema drift, bad settings/identity/data
and busy/corrupt derived indexes. No storage migration/checksum was changed.
