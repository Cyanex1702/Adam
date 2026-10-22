# Wave 9 completion report — ADAM 0.9.0

Milestones 10.0 and 10.1 are AUTOMATED_VERIFIED. Human Gate 9 is pending;
Wave 10 voice is NOT_STARTED. Source remains on C: at
`%PROJECT_ROOT%`. ADAM Desktop is installed on this PC with
a Start menu shortcut, separate from the existing ADAM store and model assets.

## Delivered

The Windows Tauri/React/TypeScript workspace provides streaming chat, resumable
conversation history, owner/demo switching, saved-memory search with provenance,
display preferences and developer diagnostics protected by fresh owner login.
The Three.js abstract orb reflects operational events, with reduced-motion and
disable options. Voice and vision remain explicitly unavailable. Existing CLI,
API, approved tools, tasks, resilience and model-migration interfaces remain.

The packaged service includes Python and its runtime dependencies, including
Qdrant/ONNX, so running the desktop requires no development environment. GGUF,
llama.cpp and E5 assets are installed separately. This PC's existing Qwen model
is used; no model migration/default change was made. Missing assets surface an
offline state. Committed memory/history stay usable independently of generation.

Rust owns the service process, private pipe handshake and bearer token. Fixed
routes, request/response limits, nonce/origin checks, authentication epochs and
stream correlation protect the bridge. Cancellation and profile changes cannot
publish stale owner replies into a different profile. Windows job ownership
cleans descendants on parent failure. No backend core module imports the UI.
No database schema change was needed. A Windows Store asset-visibility edge case
was repaired: normal desktop launches can reuse the known complete public model
cache when the primary runtime is absent. A primary runtime remains authoritative,
incomplete cache assets are refused, and personal data paths never redirect. Two
additional regression tests cover this behavior. The full packaging script was
then rerun end to end.

The unsigned current-user NSIS installer uses `%LOCALAPPDATA%/ADAM Desktop`,
separate from `%LOCALAPPDATA%/ADAM` data/assets. A hook refuses existing ADAM store
destinations. A protected synthetic destination was rejected with exit code 2,
without changing its marker. Install, uninstall and reinstall succeeded; the
existing Qwen asset's size and modification time were preserved.
The Start menu shortcut was also resolved to the physical installed executable
path and verified, addressing this Codex Store host's filesystem virtualization.

## Verification

| Check | Result |
|---|---|
| Python regression suite | 195 passed |
| Ruff lint and formatting | Passed |
| Strict mypy | 72 backend modules passed |
| Full scripted evaluation/security gate | 22 cases, zero critical failures |
| TypeScript production build | Passed |
| Frontend operational-state/preferences/error tests | 5 passed |
| Rust route/privacy/job ownership tests | 3 passed |
| cargo fmt / Clippy with warnings denied | Passed |
| Frozen service, synthetic transport | 39 checks passed |
| Frozen service, real Qwen | 43 checks passed across two lifetimes |
| Installed native host / IPC / single instance / parent crash | 16 checks passed |
| Browser UI observations | 16 flows passed |
| Installer guard / install / uninstall / reinstall | Passed |

Executable tests use disposable stores, synthetic credentials and fixture data.
Native-host lifecycle tests deliberately use an unavailable external model alias
to isolate host/IPC behavior. The separate real-Qwen suite verifies actual
streamed completion, token events, history and memory persistence, profile
isolation, login denial and cleanup across service restarts. The synthetic probe
is explicitly labeled and is not used as evidence of model intelligence.

Browser checks covered login, keyboard send, history resume, memory provenance,
owner/demo isolation, developer reauthentication, display flags and locking.
One provenance-label issue discovered there was corrected and rechecked. The
initial native-host test harness held its own SQLite read handle open; closing
that handle fixed fixture cleanup. Installed host tests subsequently passed.

## Limits and handoff

An early real-chat attempt failed during concurrent native compilation; its cause
was not captured. A subsequent full real-model run passed without weakening the
resource policy. Sustained contention/reliability remains a manual Gate 9 check.
Browser frame observations were nominally 59–60 FPS, with 24–57 FPS dips during
build contention. Native WebView2 frame rate and native resize/minimize comfort
were not automated. Automated native checks prove production frontend IPC starts
the bundled service; they do not replace native visual/user-experience review.

The installer is unsigned. WebView2 bootstrap requires internet if that runtime
is missing; this PC already has it. Native tool-approval screens, voice, vision,
tray/background startup and automatic model downloads are not added by Wave 9.
The existing earlier interfaces continue to provide their approved operations.
Local conversation/source databases remain cleartext under the Windows account.

See `desktop.md` for setup/build, `gate-9.md` for review, and
`evidence/wave9-*.json` for machine-readable results. Milestone 10.0 checkpoint:
`d325c9b`; milestone 10.1 closes in the following avatar verification checkpoint.
