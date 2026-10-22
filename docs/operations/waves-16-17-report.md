# Waves 16 and 17 - ADAM Desktop 0.17.0

The user explicitly authorized both waves together on 2026-10-15. The paired
release implements milestone 17.0 and milestones 18.0-18.2 within the scope in
[Computer actions](computer-actions.md) and [Setup and recovery](distribution.md).
Earlier pending human gates remain pending. Gates 16 and 17 are NOT_STARTED.
Wave 18 has not started. ADAM Desktop 0.17.0 is built and installed on this PC.

Wave 16 adds an owner-only standard Win32 provider, live screenshots/OCR,
explicit window/control selection, bounded multi-step plans, previews, dry-run,
once-only digest approval, reauthentication, post-step screenshot/control-state
verification, cancellation and uncertain outcomes after dispatch. Sensitive
applications, fields, labels, duplicate actionable labels and unsupported
interfaces are denied. There is no global input or chat/model action authority.
Payloads are RAM-only; audit uses metadata. Verification covers declared native
UI state, not unobserved external effects. Editable recovery uses a new reviewed
plan; clicks have no automatic rollback.

Wave 17 adds guided hardware/model checks and pinned opt-in downloads, CPU
initial profiles, checked managed release packages and stable/beta/dev channel
selection, session-bound once-only offline activation, encrypted local snapshots,
cloned-profile migration/smoke validation, atomic generation publication,
rollback, normal-launch generation selection, encrypted portable data restore,
device reconfiguration guidance and explicit index rebuilding. Dependencies
remain bundled. No automated external update feed is configured. Windows VM,
other physical hardware, real model quality, Android re-pairing and human UI
acceptance remain unverified.

Automated source verification passed 413 Python tests, 12 frontend tests,
3 Rust tests and 22 scripted framework evaluation cases with zero critical
failures. Ruff, strict mypy (115 modules), Clippy, dependency checks and the
frontend production build passed. Existing bundle-size and TestClient
deprecation advisories remain. The final strengthened distribution suite passed
all 26 tests, including background completion, cancellation and revoked sessions.

Real native fixture QA passed 31 checks each against source, frozen and installed
services: capture/OCR, approved typing/clicking, independent control state,
dry-run, stale UI denial, ambiguous controls, password fields, private titles,
cancellation and payload-free stores. Other frozen regression receipts cover
desktop (39), vision (41), reminders (20), mobile (24) and Internet tools (36).
These use isolated fixtures and do not certify human acceptance or model quality.

All 17 packaged distribution checks passed: real candidate activation, intentionally
corrupted-schema rejection, the unchanged active pointer after failure, rollback,
encrypted snapshots, model-free restore, memory continuity and owner login.
Native lifecycle QA passed 16 checks each against installed and portable builds:
startup, loopback access, single-instance handling, store integrity, crash cleanup
and data preservation. Managed-launch and frozen offline handoff QA each passed
six checks, including generation selection and restart into the selected app.
The [final QA record](evidence/waves16-17-final-qa.json) binds these final-package
checks to the delivery hashes. Individual results are recorded under [evidence](evidence/).

The installed-upgrade check passed all five checks and preserved 25 existing
files. The Start Menu shortcut targets the installed native executable, which
selects the active managed generation. Packaging compared all 112 frozen source
modules and 895 payload files, verified archive CRCs, and excluded model weights
and private stores. [Delivery hashes and paths](evidence/waves16-17-delivery.json)
identify the final installer, portable ZIP and managed release ZIP.

Regression coverage includes stale restored-profile environment state on
rollback and approval against an outdated generation state. Model setup runs as
a cancellable background job. Its bounded pinned-download grant checks owner
session validity throughout without requiring elevation renewal mid-download.
Cancellation, revocation, expiry and app shutdown still stop it. Seven frozen
setup checks verify immediate queue/cancel without completing a large download.

Clean Windows/VM installation, another physical PC, a completed model download,
real-model quality, Android re-pairing and human UI acceptance remain pending.
Use the [Gate 16](gate-16.md) and [Gate 17](gate-17.md) checklists to record human
validation; automated evidence does not mark those gates as passed.
