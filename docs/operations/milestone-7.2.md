# Milestone 7.2 — Security and red-team release gate

Version 0.6.0 passes 114 regressions, Ruff lint/format, strict mypy and the full
22-case evaluation gate. Ten critical boundary fixtures cover prompt injection,
malicious documents, role impersonation, memory poisoning, scope escalation,
encoded exfiltration, malformed calls, approval replay, session revocation and
trace secrecy. Any critical failure makes the evaluator exit nonzero. A deliberately
vulnerable test confirms that failed cases cannot produce a passing release report.

The encoding fixtures exposed a privacy gap: registered secrets were blocked in
plain text but common encodings were not. The in-process denial cache now recognizes
Base64/URL-safe Base64, hexadecimal, URL and JSON escaping; the streaming boundary
holds partial matches, including whitespace-separated encoded prefixes. These
values are never persisted in the denial cache. This is finite coverage of known
secrets, not a general detector for unknown or arbitrarily transformed secrets.
Encoded matching applies to registered values of at least eight characters.

The developer UI rejects responses from an earlier authorization epoch after
locking, preventing late requests from restoring cleared evidence. Reports retain
fixed error codes and fixture metadata rather than private failure text. The
security dataset digest includes the attack implementation, so changed fixtures
cannot silently compare as the same baseline. No schema or authorization model changed.

See `wave-6-report.md`, `gate-6.md` and `evidence/wave6-full-eval.json`.
