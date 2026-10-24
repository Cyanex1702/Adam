# Local desktop voice

The compact configuration enables voice and uses offline Windows SAPI English
speech by default. Faster-whisper base runs on CPU with int8 weights and two
threads. Kokoro int8 remains selectable for English, French, Spanish, Italian,
Brazilian Portuguese and Hindi output. Urdu recognition is selectable; Urdu
speech output is unavailable. Recognition quality varies by language and room.
Optional speaker recognition has separate setup and consent requirements; see
[speakers.md](speakers.md). Voice recognition does not grant owner authority.

## Setup and operation

From the project directory, run `scripts/setup-voice.ps1` once. It downloads about
256 MiB of public speech assets, verifies pinned revisions and SHA-256 hashes,
and writes a manifest under `%LOCALAPPDATA%/ADAM/models/voice`. It does not enable
the microphone. The packaged app includes the speech libraries. Source developers
install `requirements.lock.txt` or the project's `voice` extra as well.

The script pins [faster-whisper base](https://huggingface.co/Systran/faster-whisper-base)
and [Kokoro ONNX release assets](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0).
Runtime inference uses local files, with no automatic model download. Supported
public asset caches can be reused; private stores stay separate.
`voice.assets_dir` can select another complete asset folder.

Open ADAM Desktop. Record voice begins capture after the Windows/browser
permission decision. Finish recording decodes locally and shows a review field
beside the raw transcript. Send reviewed transcript uses the ordinary chat path.
Text input remains available when assets, microphone or speech providers fail.

Conversation mode and Read replies aloud are separate opt-ins. Conversation
mode uses bounded rolling partial decoding, a final full decode and pause/
linguistic-completeness decisions. Incomplete sentences wait longer. Estimated
confidence below 0.65 requires review, and slash commands never auto-submit.
Confidence is an uncalibrated heuristic, not a guarantee of correctness.

The general configuration defaults to Kokoro; this PC's `adam.compact.toml`
chooses Windows speech for responsiveness. Voice settings can override either.
Windows speech is English-only and falls back between installed English accents.
Kokoro supports the listed languages, but measured synthesis was slower than
playback on this i5 under competing CPU load. The UI reports slow synthesis.
Headphones are recommended for conversation mode until acoustic echo testing.

## Boundaries and resources

Capture requests echo cancellation, noise suppression and gain control from
WebView2, with DC removal and Silero VAD in the backend. This is not a separately
trained denoising system. Audio is mono PCM16 at 16 kHz, limited to 60 seconds per
request; the UI ends capture for review at 58 seconds. Speech chunks are bounded
to 240 characters and 45 seconds of output at 24 kHz. TTS queues are bounded.
Independent serialized STT and TTS lanes allow interruption decoding during
synthesis; resource pressure refuses work rather than silently changing policy.

Hard interruption stops playback and cancels the current chat. Acknowledgements
such as mhm leave it running. Corrections cancel the prior request before sending
the corrected utterance. Rolling faster-whisper decoding is not a native streaming
decoder; recognition adds latency. An in-flight synthesis call drains before the
next call, but its obsolete output cannot play. No instantaneous spoken-stop
latency or real-world echo reliability is claimed by prerecorded tests.

Voice routes exist only behind the authenticated private desktop boundary and
native route allowlist. Recognition itself never dispatches tools or creates
chat history. Owner/demo isolation and existing approval policies apply to sent
text. Spoken names do not grant authority. Pause profiles are scoped to the
authenticated profile, bounded to 600–1600 ms, resettable and held in memory;
biometric per-speaker adaptation awaits Wave 11.

Raw capture and synthesized audio stay in RAM by default. Lock, profile changes,
hidden windows and unmount stop capture/playback and invalidate pending results.
Transcripts are not persisted until sent into ordinary conversation history.
`voice.retain_audio = true` explicitly retains final capture only in the active
profile's `voice/audio` folder. Default expiry is 24 hours and 20 files (maximum
168 hours/100 files); cleanup runs at startup and every minute while running.
Overdue files are removed at the next launch after shutdown. Partial audio is
never retained. SAPI input is literal text, not speech markup.

Test recognition and playback with your own microphone, speakers and target
languages. Public audio fixtures do not establish real-room speech quality.
