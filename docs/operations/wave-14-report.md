# Wave 14 — ADAM Desktop 0.14.0

The user's 2026-10-12 next-task request authorizes Wave 14. Implementation covers
milestones 15.0–15.2 within the explicit web-evidence, bounded HTTPS MCP tools and
HTML text-browser scope described in [the guide](internet-integrations.md).
Automated status: **AUTOMATED_VERIFIED** within the stated implementation scope.
Gate 13 remains NOT_STARTED; requesting advancement is not evidence of Android
validation. Wave 15 has not started. Gate 14 is NOT_STARTED.

## Milestone checkpoints

- 15.0: the initial retrieval layer passed 19 targeted tests before external
  provider work. Live public HTTPS retrieval passed. Wikipedia returned 403;
  this denial is preserved. Hacker News search was added and passed live QA;
  owner-selected SearXNG JSON support has a fixture-tested adapter.
- 15.1: exact provider discovery/call scope, schema validation, explicit digest
  approval, expiry, disconnect/failure, once-only execution, session isolation
  and denied server authority requests passed targeted tests. The public
  DeepWiki MCP server passed live discovery and a documentation-read call.
- 15.2: script-free HTML read/navigation/link actions, local form drafting,
  approval before submission, draft/page freshness checks, unsupported sensitive
  controls, cancellation and metadata audit passed targeted checks. Full
  graphical browser automation is outside the delivered text-browser scope.

## Changes and boundaries

New `backend/adam/internet` transport, retrieval, provider, action service and
owner API; `InternetPanel.tsx`; exact native IPC routes; truthful identity/error
copy; source/frozen QA harness and focused regressions. Version metadata is
0.14.0. JSON Schema runtime dependencies and matching development stubs are
added/pinned. No existing private database migration or backup-schema change.
Internet state is RAM-only and bound to the current owner login. Audit events
use the existing trace store without payloads. Internet starts disabled; no
model tools, automatic external watches or remote phone Internet authority.

Search coverage is explicit: Hacker News technology/community stories,
Wikipedia encyclopedia articles and an owner-supplied public SearXNG JSON
instance for general web search. No hosted search account is provisioned.
External material remains inert evidence. Secrets, local addresses, binary
downloads, credential URLs, ambient proxies/cookies and unsafe redirects are
denied. Pinned HTTPS retains original-host certificate validation.

MCP supports the documented 2025-11-25 HTTPS tools subset, not every protocol
revision/transport or credentialed integration. The client controls sends and
local capability exposure; it cannot sandbox a remote server. All provider
calls and form submissions require reviewed approval and recent reauthentication.
Unknown effects are UNCERTAIN; cancelled/sent requests are never auto-retried.
Browser actions operate on static HTML, with no JS/profile/account automation.
These are practical implementation limits, not placeholders presented as passed.

## Verification and delivery

Source and packaged checks are recorded in `evidence/wave14-*.json`. Final
source verification passed **326 Python tests**, including **48 Internet cases**;
Ruff lint/format; strict mypy across **98 modules**; pip check; **10 frontend
and 3 Rust tests**; Rust formatting/Clippy; and **22 full evaluation scenarios**
with zero critical failures. The release frontend typecheck/build passed with
a bundle-size advisory (~815 kB). Starlette's upstream TestClient deprecation
warning remains. Finite framework scenarios are not a model-quality certificate.

The source and frozen Internet harness each passed **36 checks** using real
HTTPS, public Hacker News keyword search, HTML link navigation and a public
DeepWiki read-only MCP tool. It verified owner reauthentication, exact tool scope,
schema/digest denial, preview/approval, once-only execution, disconnect, disable,
restart-default-off and local identity availability. The frozen service also
passed **39 desktop**, **20 reminders** and **24 signed mobile-client** checks.
Wikipedia search returned HTTP 403; no bypass was attempted. SearXNG and form
submission use disposable fixtures in the source tests; no account-bearing
external action was performed. Human Internet UI and private-account behavior
remain pending.
Framework tests do not establish model quality or human Android/acoustic comfort.

Human procedure: [Gate 14](gate-14.md). Setup and all supported limits:
[Internet/integrations guide](internet-integrations.md).

The current-user installer passed five preservation checks; 25 existing files
retained their recorded hashes/metadata. The installed service passed 36 live
Internet checks. Installed and portable native hosts each passed 16
lifecycle/IPC/crash-cleanup checks.
Start Menu points to the verified physical installed executable. Read-only
Windows window inventory was inspected, but no QA window remained when queried;
no screenshot or interactive Internet-view acceptance is claimed.

Delivery: `%USERPROFILE%/Documents/Codex/2026-10-05/s/outputs/adam-wave14`.
The installer and portable ZIP are recorded with SHA-256 in
`evidence/wave14-delivery.json`. All 869 portable files match their final build
sources byte for byte; ZIP CRC passed. Models/private databases are excluded.
Source checkpoint: `3a5500c` (credential hardening after initial `55ed08e`); frozen-QA checkpoint is recorded in the final delivery receipt.

Representative verification commands (from the project root):

```powershell
python -m pytest -q
python -m ruff check backend tests scripts
python -m ruff format --check backend tests scripts
python -m mypy
python -m pip check
python -m adam.evals.runner --suite full --summary --output docs/operations/evidence/wave14-evals.json
python scripts/qa-internet.py --output docs/operations/evidence/wave14-internet-source.json
.\scripts\build-desktop.ps1
```

Run commands with ADAM's verified development Python environment. Frontend:
`npm run test` and `npm run build` in `apps/desktop`. Native: `cargo fmt --check`,
`cargo test` and `cargo clippy -- -D warnings` with the desktop manifest/build
environment. The packaged harnesses accept `--service` or `--exe` and write the
checked-in disposable QA receipts. Existing private stores are not used as test
profiles. Internet is off, and owned QA processes are stopped after verification.
