# Milestone 11.0 — Local capture and speech

Implemented in release 0.10.0: explicit microphone capture, browser noise/echo
processing, DC removal, Silero VAD, local faster-whisper base int8, confidence and
raw transcript review, bounded Kokoro TTS and an offline Windows English adapter.
Text remains available on failure. Configured raw retention is off by default;
enabled retention is profile-scoped, time/file bounded and excludes partials.

Automated verification: `tests/test_voice.py`, `src/voice.test.ts` and
`scripts/qa-voice.py`. Real source-service evidence has 32 checks, zero word error
on its clean/quiet/10 dB noise fixture, an appropriately reviewed noisy result,
and 538.9 MiB service-process-tree RSS. This is not clean-room microphone proof.
Public fixture provenance and measured performance are in
`evidence/wave10-real-voice-source.json`. Packaged verification follows in the
Wave 10 report. Gate 10 acoustic acceptance remains pending.
