# Wave 15 - ADAM Desktop 0.15.0

The user's next-task and completion requests authorize Wave 15 while Gate 14
remains pending. This release covers milestones 16.0-16.1 within the explicit
image OCR, selected-window text understanding and optional local visual-model
adapter scope in [the guide](vision.md). General scene quality, camera input,
continuous monitoring and action execution are outside the verified scope.
Gate 15 is **NOT_STARTED**. Wave 16 has not started.

## Implementation

Owner-only Vision API and desktop view, native IPC allowlist, bounded static
image normalization, real Windows OCR, an optional loopback-only multimodal
adapter, and explicit one-window capture. Capture runs in an isolated Windows
job with bounded startup/render time and a visible non-activating notice.
Application identity, window identity, private titles and display affinity are
checked before and after rendering. Unsupported windows fail closed.

Vision starts off, consumes each screen opt-in once, uses session/epoch guards,
and clears on disable or leaving/hiding the view. Authentication revocation
invalidates work. Persistent traces contain metadata without images, OCR or
window titles. No database migration or model download is required.
Results carry uncertainty and no action authority. Existing ordinary chat does
not claim to receive images. The local visual-model adapter requires the
server to advertise vision before image transmission and rejects tool calls.

During live QA, repeated native window-class registration failed. The notice
now uses one service-owned message-pump thread, shows only during capture, hides
after completion/cancellation, and is released on service exit. Cancellation
tests verify the visible state rather than assuming an absent HWND.

## Verification

Source: **369 Python tests**, including **43 Vision cases**; **12 frontend** and
**3 Rust** tests; **22 evaluation scenarios**, zero critical failures. Ruff,
strict mypy (105 modules), Clippy and dependency consistency pass. The frontend
build passes with the existing bundle-size advisory; Starlette emits its
upstream TestClient deprecation warning.

The source Vision harness passes **39 live checks**, including actual Windows
OCR, a synthetic selected window, private-title denial, repeated capture,
non-activating notice, cancellation, restart-default-off and payload-free stores.
No personal application content was captured. Model-adapter tests use fixtures;
no multimodal model quality is established on the i5/16 GB/Quadro PC.

Automated status: **AUTOMATED_VERIFIED** within the stated scope. The final
clean frozen backend passes **39 Vision checks**. The installed service passes
**41 checks**, including native-style parent ownership and nested capture-worker
jobs. Installed and portable native hosts each pass **16 lifecycle/IPC checks**.
The upgrade passes **5 checks**, preserving existing database hashes and model
metadata. Start Menu resolves to the verified PC installation.

Earlier packaged regressions also pass: **39 desktop**, **20 reminders**,
**24 signed mobile-client**, and **36 Internet** checks. Source Internet QA
passes **36 checks** after the authentication-handler change. These suites use
disposable stores and synthetic/public inputs; no model-quality run or human
native UI acceptance is implied.

The first packaging pass retained stale notice text in its build cache. A clean
PyInstaller build resolved it. Every frozen Vision module is compared against
compiled final source. The release script now always clears that cache.

The final installer and portable ZIP are in the task output `adam-wave15` folder.
The ZIP contains **890 files**, each compared with the verified build or included
guide source, and passes ZIP CRC verification. SHA-256 sums accompany the
artifacts. External model weights and private SQLite stores are excluded.
Receipts are under `docs/operations/evidence/wave15-*`. Delivery completed on
2026-10-13. Human Gate 15 and earlier pending human gates remain NOT_STARTED.
