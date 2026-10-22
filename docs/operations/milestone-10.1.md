# Milestone 10.1 — Abstract operational avatar

Status: AUTOMATED_VERIFIED, 2026-10-07. Human Gate 9 pending.

The Three.js shader orb consumes serialized events through the UI bridge; no
agent/runtime imports enter the renderer. Request preparation, model thinking,
retrieval, tool activity, permission waits, uncertainty, errors and connection
state have explicit mappings. Deterministic memory commands do not claim the
model is generating. Unknown events preserve state; future voice events cannot
fabricate listening or speaking. No emotion/personhood signals are implemented.

The renderer uses a small 256-pixel canvas, bounded pixel ratio, low-power GPU
preference, modest geometry and no antialiasing. It pauses on document hiding and
disposes its GPU resources on disable/unmount. Reduced motion renders a static
orb that still changes color with actual state. A CSS orb is available when
WebGL initialization fails. Flags persist only display booleans in local storage.

Five frontend tests cover these event/privacy/error/preference rules. Browser QA
on this i5/16GB/Quadro PC observed nominal 59–60 FPS, and 24–57 FPS during concurrent
compilation/contention. These are rolling browser frame-counter observations,
not sustained native WebView2 measurements. The target is 60 FPS under normal
use; no all-load frame-rate guarantee is claimed. Native comfort and sustained
performance remain explicit Human Gate 9 items.

The milestone 10.0 checkpoint is `d325c9b`. Final Wave 9 evidence and limitations
are recorded in `wave-9-report.md`. The installed app was tested separately from
the browser fixture for actual IPC, backend ownership and parent-crash cleanup.
