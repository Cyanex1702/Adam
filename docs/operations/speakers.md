# Local speaker recognition — Wave 11

The compact desktop configuration enables advisory speaker recognition. Run
`scripts/setup-speakers.ps1` once to verify/download TitaNet small and pyannote
segmentation 3.0 int8 from the official sherpa-onnx release assets. The runtime
uses CPU inference with bounded threads. Existing STT/TTS assets are installed
by `scripts/setup-voice.ps1`. Missing speaker assets fail closed; text remains usable.

Open Developer view and unlock it with your owner password, then return to Chat.
Expand Speaker recognition and enrollment. Enter a label, choose owner or guest,
and consent to storing the speaker's template. Record 6–20 seconds of continuous,
clear speech with only that person present; finish the recording. Enrollment
requires at least four seconds of detected speech and consistent embeddings.
One owner and at most eight total templates are allowed. Remove the existing
owner template before replacing it. Reauthentication expires after five minutes.

Templates contain normalized embeddings encrypted with Windows current-user
DPAPI, tied to the model identifier and authenticated ADAM profile. API metadata
contains labels and roles, never embeddings. Enrollment recordings are discarded.
Ordinary raw-audio retention remains off by default. Optional transcription
retention follows the existing voice policy; it does not enable enrollment audio
retention. Template labels and SQLite metadata are cleartext. An application
running under the same Windows account can access DPAPI; this is not protection
against a compromised account. Templates are excluded from portable backups;
re-enroll after restoring onto another installation. Remove template revokes its
future matching; already-displayed transcript labels are historical observations.

Record voice / Finish recording shows speaker matches and individual timed
utterances. Unknown or guest voices require manual review. Multiple speakers
produce separate review streams and an empty combined transcript. Select the
intended speaker's words, check/edit them and send deliberately. Detected overlap
is not transcribed into a combined command: ask each person to repeat separately.
This implementation does not separate inseparable overlapping voices.

Conversation mode requires a completed owner match, adequate speech confidence
and an ADAM address word. Push-to-talk is an explicit address signal. Short clips
may remain unknown even for enrolled speakers. Diarization, overlap detection,
address heuristics and cosine match scores can be wrong. Scores are uncalibrated
similarities, not biometric probabilities. Pause learning stays bounded in memory
and scoped to authenticated profiles; it does not persist biometric timing habits.

Voice never authenticates, elevates, changes the session principal or bypasses
existing action approvals. A recording or cloned voice can match an owner.
Only exact normalized audio repeated within ten minutes and still present in the
bounded 128-entry in-memory history is flagged as replay;
other replay risk is explicitly NOT_RULED_OUT. No liveness or clone defense is
claimed. Owner passwords/device/session boundaries remain authoritative.

Spatial audio is DEFERRED_MONO_CAPTURE. Direction/distance are not fabricated.
Public recorded English fixture QA does not replace [Gate 11](gate-11.md).
Models: [speaker identification example](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/speaker-identification.py)
and [diarization models](https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/models.html).
