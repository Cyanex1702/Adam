# Wave 11 — ADAM Desktop 0.11.0

Milestones 12.0 and 12.1 implement advisory speaker recognition and conservative
diarization/overlap review and are AUTOMATED_VERIFIED within the limits below.
Milestone 12.2 spatial audio is DEFERRED_MONO_CAPTURE.
Human Gate 11 is NOT_STARTED. The user's request on 2026-10-08 authorizes
progression without representing Gate 10's unperformed acoustic checks as passed.

## Delivered behavior

Local CPU TitaNet small embeddings and pyannote segmentation support owner/guest
templates and timed per-speaker streams. Enrollment requires explicit consent,
6–20 seconds of suitable single-speaker audio and fresh owner reauthentication.
Templates are model-bound, encrypted with Windows current-user DPAPI, scoped to
the authenticated profile and revocable. No enrollment recording is retained.
At most one owner and eight total templates are allowed.

Voice matches never grant authority or change Principal. Unknown/guest voices,
short uncertain clips, overlapping speech and repeated audio require review.
Conversation mode also requires an ADAM address word. Multiple speaker streams
are never merged into an automatic command; detected overlap asks people to
repeat separately. The desktop lets users select and review a speaker's words.
The implementation does not recover separate words from inseparable mixtures.

The native bridge permits only the fixed enrollment/revocation/status routes.
Private capability, authenticated session, fresh password elevation, bounded
audio bodies, serialized speech inference and pre-commit authority checks retain
the existing security boundary. Speaker templates are excluded from portable
backups; labels and database metadata remain cleartext under the Windows account.

## Automated verification

Source speaker QA passed 22 checks against public recordings and an actual
encrypted disposable template. A 16-second two-person fixture produced two
clusters in 2.351 seconds including embedding checks; held-out same-speaker cosine
similarities were 0.755 and 0.826, versus 0.028–0.146 across speakers. A synthetic
simultaneous mixture was detected as overlap. These are small English fixtures,
not general accuracy or multilingual guarantees.

Several short segments of an enrolled public recording scored below the 0.7
recognition threshold and remained unknown. Other segments matched the owner.
The complete recording still required review because uncertainty was preserved.
Enrollment consistency uses a separate within-sample heuristic of 0.6; neither
threshold is a calibrated probability. Exact repeated normalized audio is flagged
for ten minutes; clones and other recordings remain NOT_RULED_OUT.

The first frozen QA run reached its background-speech check before resource
pressure during compilation refused further inference. The guard was not changed.
A first combined real-Qwen run also hit resource pressure. The harness now
releases its duplicate speaker sessions before launching the app, reducing
measurement overhead without changing application limits.
Browser inspection was attempted twice, but the in-app browser failed to attach;
no Wave 11 visual UI pass is claimed. Frontend tests and TypeScript build are
separate evidence. Installed lifecycle testing does not validate microphone input.

Final package and check receipts are recorded in `evidence/wave11-*.json`.

| Check | Result |
|---|---|
| Python regression suite | 230 passed |
| Frontend tests / TypeScript production build | 10 passed / passed |
| Ruff lint/format / strict mypy | Passed / 80 modules passed |
| Rust privacy/routes/job ownership, fmt and Clippy | 3 passed; passed |
| Evaluation/security gate | 22 cases; zero critical failures |
| Real source / frozen speaker service | 22 / 22 checks passed |
| Real speakers → reviewed text → Qwen → Windows PCM | 25 checks passed on rerun |
| Same real speaker/Qwen/PCM suite from installed backend | 25 checks passed |
| Frozen desktop transport and profile lifecycle | 39 checks passed |
| Installed native lifecycle / existing-data upgrade | 16 / 5 checks passed |
| Installer / portable archive | Built; CRC and source-byte comparison passed |

Frozen speaker/STT service memory was 573.2 MiB RSS. The combined real Qwen,
speaker/STT and Windows speech service process tree used 3440.5 MiB RSS after
completion; the installed run measured 3422.4 MiB. These snapshots exclude the
UI and QA harness and do not establish
long-session peak memory. Frozen enrollment took 2.315 seconds on the public
10-second fixture. Runtime models remain outside the installer; approximately
40 MiB of speaker weights were added to this PC's public asset directory.
Sherpa distribution/license metadata is included in the packaged backend.
The upgrade preserved hashes/metadata for 25 existing database and public-model
files. The Start menu shortcut points to the verified physical installed EXE,
including this PC's Windows Store LocalCache path correction. The portable ZIP
contains 832 files and excludes models and personal data. Delivery is under
`%USERPROFILE%\Documents\Codex\2026-10-05\s\outputs\adam-wave11`; SHA-256 hashes
are in its `SHA256SUMS.txt`. Source checkpoint: `a1872bd`.

## Human handoff

Follow [speaker setup](speakers.md) and [Gate 11](gate-11.md) with two consenting
people, a real microphone and headphones. Test background conversation, overlap,
unknown guests, replay/clone attempts and privileged commands. Short voices may
need manual review; a match is never authentication. Speaker/profile pause
learning remains bounded in memory at the authenticated profile level.

Gate 10's earlier intermittent reply-to-PCM failure remains an observation to
watch in real use; its uncaptured original cause was not fixed by this wave.
The installer is unsigned. Spatial audio requires suitable array hardware and
separate validation. Wave 12 mobile/device mesh has not started.
