# Wave 13 — ADAM Desktop 0.13.0

The user's next-task request and “complete the job” authorize Wave 13 on
2026-10-10. Milestones 14.0–14.2 are implemented within the reminder-job and
in-app notification scope below. Human Gate 13 is **NOT_STARTED**; previous
Android/acoustic gates are not inferred passed. Later waves were not started.

## Delivered behavior

Persistent owner reminders support once, delayed and fixed-interval schedules.
SQLite transactions atomically create an update and advance the job. Restart
catch-up coalesces missed repeats; clock rollback cannot duplicate completed
occurrences. Request IDs deduplicate creation even after the original time;
conflicting payloads are denied. Cancellation withdraws pending/future delivery.
Background execution rechecks persisted enablement. Owner mutations recheck
current authority after acquiring the database transaction. Guest/demo/mobile
clients cannot create/configure/acknowledge reminders. Inputs reject naive dates,
likely credentials, control characters and oversized text. Storage/queue bounds
apply backpressure; acknowledged/completed data is pruned after 30 days.

Notification routing follows explicitly selected conversation ownership and a
recent signed mobile status poll. Stale/offline/revoked/handoff devices redirect
the same pending update to the PC. Priority orders inbox offers; quiet hours
suppress every priority without dropping updates. Mobile offers are generic
and exclude reminder text/session IDs. Full content appears only in the owner
PC inbox. Visibility/epoch guards clear or suppress stale UI state.

The registered `unread_reminders` condition reads only the owner reminder inbox.
It needs explicit opt-in, a 24-hour unread condition, a 24-hour cooldown and an
open quiet-hours window. Every suggestion explains its cause. Disabling it
withdraws pending suggestions. No background model/tools, external messages,
file/browsing/microphone watching or captured login tokens are used.

The optional store fails closed on damage or refused linked paths while local
chat remains available. The desktop UI has a Reminders view and generic pending
badge; the signed Android client polls generic alerts. Native IPC permits only
fixed operations routes; arbitrary/parameterized paths remain denied.

## Practical limits

Scheduled jobs are reminders, not autonomous saved tool plans. Use existing
explicit PC task/action approval to execute tools. ADAM must be running: no OS
wake-up service, background Android worker or OS push notification is installed.
Mobile alerts need the trusted browser visible. Delivery is an inbox offer, not
a physical playback/lock-screen acknowledgement. Fixed intervals and explicit
quiet-hour UTC offsets need manual adjustment for travel/daylight saving.
The existing encrypted backup format excludes `operations/jobs.sqlite3`; the
setup guide explains a closed-app manual whole-data-folder copy. These limits
are part of this implementation, not claims that unimplemented channels passed.

## Verification

The full source suite passed **278 Python tests**, including 21 operations cases
and 27 mesh cases. Edge cases cover concurrent duplicate tickers, atomic restart,
missed repeats, rollback, cancellation, pause/resume, priority/quiet suppression,
idempotent late retry, unsafe inputs, permissions, opt-in/rate limits, queue
backpressure, corrupt-store local-chat preservation and signed mobile redaction/
revocation fallback. Ruff formatting/lint and strict mypy across 92 modules passed.
The frontend passed 10 tests and production typecheck/build; Rust passed 3 tests,
formatting and Clippy. All 22 full scripted evaluations passed with zero critical
failures. These are finite framework scenarios, not model-quality certification.

Live source operations QA passed 20 checks against a disposable sidecar across
two process starts. It observed real worker dispatch and preserved job/inbox
state, idempotency, invalid-date rejection, pause, guest denial, acknowledgment,
cancellation and clean process shutdown. Final packaged/installed receipts are
recorded in `evidence/wave13-*.json` after delivery verification.

The final frozen service passed 20 operations checks, 24 signed mobile-client
checks and 39 desktop transport checks. The mobile harness executes the bundled
JavaScript RPC code with real Node WebCrypto and trusted loopback TLS; its
DOM/IndexedDB are test doubles. Four new checks observed a scheduled mobile alert,
redacted signed contents, suppression of the PC offer while the phone is active,
and cancellation withdrawal. Source checkpoint: `7f5ebf2`; QA checkpoint: `ed599ec`.
The scheduler does not call a model, and these packaged tests use the explicit
scripted probe; earlier real Qwen/Whisper/speech receipts belong to Wave 12.

Final current-user installation passed 5 upgrade checks and preserved 25 existing
files. The installed backend matches the final frozen service; its native binary
matches the release build except Tauri's exact NSIS bundle discriminator. The
installed operations service passed 20 live checks and the native host passed
16 lifecycle/IPC/crash-cleanup checks. These use disposable profiles; they do not
enable suggestions, create reminders or start a listener in the user's private
profile. The Start Menu shortcut points to the physical installed executable on
this Windows Store host. Existing private stores were checked, but no existing
personal reminder database was present before this first Wave 13 upgrade.

Delivery: `%USERPROFILE%\Documents\Codex\2026-10-05\s\outputs\adam-wave13`.
The installer is 102,264,900 bytes; the portable archive is 143,088,490 bytes.
All 835 portable files passed source byte comparison and the ZIP CRC check.
SHA256SUMS.txt and `evidence/wave13-delivery.json` contain the final hashes.
Models and private stores are excluded. The app and QA sidecars are left stopped;
the mesh listener defaults off and proactive suggestions default off.

Interactive browser QA could not attach a Codex webview; opening the QA view was
queued, so no visual/browser-interaction pass is asserted. Its owned disposable
fixture was stopped. Actual native/Android comfort and lock-screen testing remain
human tasks even when native lifecycle and signed-client protocol checks pass.

## Human handoff

Open Reminders in the installed app. Follow [personal operations](personal-operations.md)
and [Gate 13](gate-13.md). Keep the mesh listener off until deliberately using
trusted Android HTTPS setup. Proactive suggestions start off; no settings in the
user's private store were enabled by synthetic QA.
