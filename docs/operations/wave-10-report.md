# Wave 10 — ADAM Desktop 0.10.0

Milestones 11.0–11.2 are implemented and AUTOMATED_VERIFIED.
Human Gate 10 is NOT_STARTED. The user explicitly requested the next wave on
2026-10-08, authorizing progression beyond Wave 9 without claiming its unobserved
native comfort checks passed. Wave 11 has not started.

## Delivered

The desktop now supports explicit local microphone capture, reviewed transcripts,
optional pause-aware conversation, partial recognition, chunked spoken replies,
Stop/correction/acknowledgement handling and actual audio-driven avatar activity.
Recognition uses faster-whisper base int8 with Silero VAD. WebView capture requests
noise suppression and echo cancellation; the backend removes DC offset.

This PC's compact configuration defaults to offline Windows English speech.
Kokoro int8 is selectable for multilingual output. Assets are downloaded once by
the revision/hash-pinned setup script; runtime inference remains local. No
microphone is activated by installation or startup. Text remains available.

Voice uses the existing private authenticated desktop bridge. Body/response
limits, bounded independent STT/TTS scheduling, confidence gating, stale-result
invalidation, profile isolation and optional expiring raw retention preserve
existing boundaries. Recognition itself does not execute actions or create
history. Raw audio retention is off by default. No database migration was needed.
Speaker recognition, diarization, vision and voice-derived authority are absent.

## Verification

| Check | Result |
|---|---|
| Python regression suite | 222 passed |
| Ruff lint/format | Passed |
| Strict mypy | 78 modules passed |
| Scripted evaluation/security gate | 22 cases, zero critical failures |
| Frontend tests / TypeScript production build | 9 passed / passed |
| Rust route/privacy/job ownership tests | 3 passed; fmt/Clippy passed during implementation |
| Real source speech service | 32 checks passed |
| Real frozen speech service | 32 checks passed |
| Installed speech → real Qwen → PCM flow | 31 checks passed on rerun |
| Frozen synthetic transport / real Qwen | 39 / 43 checks passed |
| Final UI observations | 11 passed |
| Installed native lifecycle / upgrade checks | 16 / 5 passed |

Frozen speech metrics: zero word error on the 11-second public JFK clean/quiet/
10 dB synthetic-noise fixture. Clean decoding took 9.522 s, quiet 5.094 s, noise
2.973 s during build contention. The noisy result had confidence 0.634 and required
review. Silence produced no transcript; partial recognition was explicitly
labeled and also required review. This small English fixture is not a multilingual
accuracy estimate. Source-service clean decoding took 4.984 s.

Frozen Windows speech generated 4.035 seconds of PCM in 0.292 s (RTF 0.072).
Kokoro generated 2.624 seconds in 17.672 s cold / 8.537 s warm (RTF 6.735 / 3.254).
The real speech service process tree used 541.7 MiB RSS after both engines loaded.
These measurements exclude the separate LLM and UI processes and are snapshots,
not long-session peak-memory guarantees. The PC had competing Java/build load;
no unrelated application was stopped to improve results. Slow Kokoro synthesis
is surfaced in the UI, and Windows speech is the compact default.

An early full real-Qwen run was refused with RESOURCE.PRESSURE during compilation
and UI testing. Its resource guard was not weakened. The post-build rerun passed
all 43 real-Qwen checks across two service lifetimes. A dependency incompatibility with PyAV 19 was
fixed by pinning the compatible PyAV 16.1.0 and exercising the frozen decoder.
UI QA also found and fixed a 720-pixel-height sidebar overflow that displaced the
header; the sidebar now scrolls independently.

## Limits and handoff

Pause adaptation follows authenticated profiles, not biometric speakers. Turn
probabilities and confidence are heuristic. Rolling STT re-decodes a bounded
utterance and can add seconds of interruption latency. Stop cancels playback
immediately, but synchronous synthesis drains in the background before the next
chunk. No instantaneous spoken-stop timing is promised.

No real microphone permission/capture, room acoustics, code-switch accuracy,
speaker echo or extended conversational comfort was tested by automation.
Read [Gate 10](gate-10.md) before treating voice as accepted for everyday use.
The installer is unsigned. Local databases remain cleartext under Windows.

Run ADAM Desktop from Start, select Record voice, speak and Finish recording,
then review and send. Conversation mode and read-aloud are separate opt-ins.
Use headphones first. Operational details are in [voice.md](voice.md).
Backend/turn checkpoint: `a45280e`; UI/package completion follows this report.
UI/streaming checkpoint: `96f2928`. Machine-readable receipts are in
`evidence/wave10-*.json`; the source checks receipt distinguishes the earlier
passing Rust checks from a redundant rebuild stopped during resource contention.

The final unsigned NSIS installer and portable ZIP are delivered under
`%USERPROFILE%/Documents/Codex/2026-10-05/s/outputs/adam-wave10`, with SHA-256 sums.
The current-user installation was upgraded, database hashes/model metadata were
preserved, and installed code/configuration matched the final build. Binary
comparison accounts only for Tauri's exact three-byte NSIS bundle discriminator;
an initial byte-for-byte check caught this expected packaging difference.
Installed native startup, private IPC, single-instance handling, integrity and
parent-crash cleanup passed. The Start menu shortcut points to the verified
physical installed executable, addressing Codex Store virtualization.

The combined installed-service suite also passed 31 checks with real recognition,
Qwen completion and synthesis of the actual reply using Windows speech. Its
owned process-tree RSS snapshot was 1744.7 MiB; this excludes GPU memory and is
not a peak measurement. An initial combined attempt reached Qwen completion but
failed the response-to-PCM assertion. That harness did not capture the original
error code. Failure diagnostics were added, and the rerun passed without changes
to application code. The cause remains unconfirmed; do not infer sustained
reliability from this one passing short flow. Gate 10 must exercise longer use.
