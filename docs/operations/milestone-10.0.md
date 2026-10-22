# Milestone 10.0 — Tauri desktop application

Status: AUTOMATED_VERIFIED, 2026-10-07. Release 0.9.0.

The Tauri 2 / React / TypeScript Windows app provides streaming chat, saved
conversation history, owner/demo selection, memory search with provenance,
display settings and freshly authenticated developer diagnostics. Its bundled
Python service removes the need to orchestrate Python or model processes in a
terminal. The initial abstract orb is included; avatar acceptance is recorded
separately at the milestone 10.1 checkpoint.

The native bridge keeps bearer credentials and a pipe-issued private service
capability in Rust. It has a fixed route allowlist, bounded messages, correlated
streams, cancellation and authentication epochs. The private service refuses
browser origins and exposes one-time credential setup only to its native bridge.
The normal API has no setup authority. An existing owner passphrase is preserved.
Closing/crashing the host cleans up its own process tree through a Windows job;
it does not adopt or kill unrelated model processes. Restart locks the UI.

The current-user NSIS installer installs app binaries under a separate
`%LOCALAPPDATA%/ADAM Desktop` directory. It rejects a destination containing an
ADAM store. Installed models and owner data remain under ADAM's existing root.
The Start menu shortcut was verified. The app and installer are unsigned.

Verification: 193 Python regressions, Ruff/format, strict mypy on 72 modules,
22 scripted evaluation/security cases, TypeScript production build, four frontend
state tests, three Rust tests, cargo fmt and Clippy with warnings denied pass.
The frozen executable passes 39 synthetic checks and 43 real-Qwen checks across
two service lifetimes. The installed host passes 16 process/bridge checks across
two launches. Installer guard and successful installation were exercised.
Browser UI observations cover 16 flows. Evidence is under `evidence/wave9-*.json`.

Native host checks deliberately use an unavailable synthetic external model
alias in a temporary profile; the real-model suite is separate. Native UI input,
window ergonomics and sustained WebView2 frame rate still need Human Gate 9.
No personal profile was used for automated QA. No schema migration or backend
dependency on the UI was introduced. Wave 10 voice is not started.
