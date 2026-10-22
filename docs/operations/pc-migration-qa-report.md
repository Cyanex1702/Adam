# PC migration and QA — 2026-10-06

The active project is now `%PROJECT_ROOT%`. The complete source,
Git history, local configuration and existing project data were copied and 636 files
were verified by SHA-256 with zero mismatches. Only rebuildable caches, build output
and the unused USB virtual environment were excluded. The USB original was renamed
to `F:\Project Adam USB Backup 2026-10-06` and retained. Python's editable installation
now points at the PC source; the former active USB path is absent during the live QA.
Existing models and personal runtime data stay under LocalAppData on C:.

Runtime/package 0.4.1 includes two fixes found while checking the move and edge cases:

- Streaming redaction buffers a possible known-secret prefix across model tokens so
  a later secret-bearing chunk cannot leave its earlier prefix exposed. A regression
  test splits a registered value across three chunks and verifies no prefix is emitted
  and no failed turn is committed.
- Startup resolves a stale config path for this moved project to the local copied
  file. An unrelated missing custom config fails explicitly; an existing custom config
  remains authoritative. Both start.ps1 and dev.ps1 use the same resolver.

| Verification | Result |
|---|---|
| Source/Git/data copy hashes | 636 files verified, no mismatches |
| Regression and new edge cases | 76 passed |
| Ruff lint, formatting and strict mypy | Passed |
| Live PC startup/API/model/terminal/session checks | 48 distinct checks passed across primary and follow-up runs |
| Real model | Qwen3-4B owner recall and adversarial guest isolation passed; six provider requests observed |
| Real CPU embeddings | Demo grounding and unsupported-answer abstention passed |
| Captured adversarial provider inputs in regression tests | Twelve constructed requests excluded owner-private content |

Edge cases include token expiration/revocation, logout, wrong passwords and throttling,
forged bearer credentials despite a valid cookie, guest/demo profile isolation,
profile-path injection, concurrent session locks/cancellation, context overflow,
malformed/empty/truncated provider streams, stale sources, missing knowledge, secret
chunk boundaries, locked/unavailable/tampered vaults, stale configuration paths and
copy/startup without the former active USB folder. A revoked generation cannot commit
a turn, and revoked WebSockets close before accepting another memory command.

The initial live harness expected `ABSTAINED`; the public contract actually uses
`ABSTAIN`. The corrected follow-up verified that result, WebSocket sequencing,
revocation, history preservation and logout against the real server. No unresolved
product failures remain in the checked scenarios. All QA used synthetic isolated data,
and no production owner password or secret was initialized or changed. Test servers
and the model process owned by the startup helper were stopped cleanly.

Evidence: `docs/operations/evidence/pc-migration-qa.json`. These finite tests do not
establish every possible model behavior. Conversation/source stores remain cleartext
under the current OS account; guest mode does not protect against unrestricted access
to that account's shell or filesystem. Gate 4 human validation is still pending and
Wave 5 has not started.

Start from PowerShell:

```powershell
Set-Location -LiteralPath '%PROJECT_ROOT%'
.\scripts\start.ps1
```

For a fictional demo, use `scripts\start.ps1 -Mode demo`. For repeatable automated QA,
run `scripts\check.ps1` from this directory. The updated Gate 4 guide uses PC paths.
