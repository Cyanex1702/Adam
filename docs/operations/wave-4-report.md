# Wave 4 implementation report

Milestones 4.0, 4.1 and 4.2 were implemented sequentially and checkpointed after
automated verification. Runtime/package 0.4.0. Core schema stays at 6; the separate
authentication and vault databases each use a version-1 checksummed migration ledger.
Wave 3 acceptance was recorded from the user's request to begin the next task.

Implementation status: **AUTOMATED_VERIFIED**. Human Validation Gate 4: **NOT_STARTED**.
Wave 5 has not started.

Implemented:

- Deterministic sensitivity, audience, subject, disclosure-controller and profile
  policy, applied before memory matching, source retrieval and model context.
- Owner authentication, expiring hashed bearer tokens/cookies, persistent throttling,
  logout/revocation, authorized mode switching and fresh developer reauthentication.
- Physically separate guest/demo databases, source directories and indexes, with
  generated fictional demo samples and mode indicators in terminal and API.
- Current-user Windows DPAPI and a password-encrypted Fernet/Argon2id fallback vault,
  opaque handles, purpose-scoped privileged backend consumers and fail-closed errors.
- Secret ingress/context filtering, redacted wrappers, NEVER_LOG omission and a
  WebSocket revocation check before accepting another command or persisting generation.

| Verification | Result |
|---|---|
| Complete regression suite | 70 passed |
| Ruff lint/format and strict mypy | Pass; 40 runtime source files type checked |
| Real Qwen/E5 and loopback API | 35 assertions passed, including owner recall and six adversarial mode prompts |
| Final live WebSocket/release follow-up | 10 assertions passed; version 0.4.0, authentication, revocation, logout and graceful shutdown |
| Actual start.ps1 demo/guest terminal | 8 assertions passed; owner database never opened |
| Captured mocked adversarial provider requests | 12 requests exclude owner-private context |
| Windows/fallback encryption tests | Both backends pass scope, restart, unavailable-storage and ciphertext-binding checks |

Evidence: `docs/operations/evidence/wave4-verification.json`. The live harness first
expected a memory receipt to contain a single event; the corrected follow-up verified
the documented started/token/completed sequence. Real revocation then exposed a
duplicate-close error; it was fixed and the live checks and full regression suite
passed again. All live data was synthetic and stored beneath this task's work directory.
Production owner passphrases/secrets were not initialized or changed by these tests.

Intentional API change: Wave 3 unauthenticated callers now need an owner login or
guest/demo grant. Developer and vault routes require reauthentication for five-minute
elevation. Local owner CLI/direct SDK continues to trust the operating-system account.
The startup helper verifies locked dependencies and upgrades an older environment on
the next run; the new cryptography dependencies may require internet once.

Limits: access control does not encrypt ordinary conversations or source originals,
and cannot isolate a guest with unrestricted access to the owner's Windows account.
No remote authentication/TLS, raw-secret HTTP endpoint or general tool runner exists.
Known/declared secrets are filtered; unknown arbitrary secret strings cannot be
reliably inferred. Deleted/older external files, backups and forensic RAM/disk remnants
are outside this vault's protection. Demo profiles persist separately on disk; this
alpha does not automatically purge expired profile directories. Finite tests establish
a regression baseline, not an unlimited privacy or model-behavior guarantee.

Use `docs/operations/gate-4.md` for owner/guest/demo, adversarial, elevation and vault
testing. Human acceptance is required before the next implementation wave.
