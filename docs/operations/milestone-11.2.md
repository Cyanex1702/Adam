# Milestone 11.2 — Streaming and interruption

Implemented in release 0.10.0: rolling partial STT, full final decode before
automatic send, sentence-chunk TTS, bounded output queue, hard stop, correction,
acknowledgement classification and playback cancellation. Recognition and
synthesis have separate bounded serialized lanes. Corrective requests wait for
the prior chat cancellation. Generation checks suppress obsolete audio/transcripts
after stop, lock, profile changes and unmount. The avatar uses real PCM energy.

Regression tests prove interruption decoding proceeds while synthesis is blocked,
low-confidence speech does not auto-dispatch, mhm is an acknowledgement, stop
is a hard interruption, and stopping clears the queue and invalidates in-flight
audio. Private route/authentication and body bounds are tested separately.

Partial decoding re-runs faster-whisper on the bounded rolling utterance; it is
not token-native STT streaming. A running synchronous TTS call drains without
playing its stale output. Spoken-stop timing and speaker echo need Gate 10;
the visible Stop button remains immediately available. Multi-speaker handling
and speaker-derived authority are outside this milestone.
