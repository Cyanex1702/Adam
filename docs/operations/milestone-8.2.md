# Milestone 8.2 - Human Data Export

The export service produces JSON, metadata-first JSONL, Markdown summaries and
CSV with a verified checksum manifest. Owner-authorized memories, historical
tiers, unconfirmed candidates, conversations, source metadata and task/action
receipts preserve their recorded timestamps, provenance and epistemic status.
No model call is involved. Fresh-directory staging prevents overwriting an
existing export, and publication checks current request authority.

Person, project-label, date, memory-type, conversation and task filters select
records using existing contracts. Missing action timestamps are explicitly
marked and excluded from date-filtered exports. Credential-bearing records and
denied subjects are omitted; recognized transcript secrets are replaced. Vault,
authentication, profile stores and working instructions are excluded. CSV formula
protection preserves canonical values inside JSON record fields.

Recovery export uses immutable read-only SQLite connections, marks unreadable
sections partial and does not migrate or initialize stores. Record, scan and byte
limits fail rather than silently truncate. Tests cover all formats, selective
filters, provenance, candidate uncertainty, secrets, policy denial, recovery,
fresh-directory rules, output failures, limits and authenticated downloads.

Detailed operation, limitations and purge scope: [Gate 7](gate-7.md).
