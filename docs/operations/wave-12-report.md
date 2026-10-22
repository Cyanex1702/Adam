# Wave 12 — ADAM Desktop 0.12.0

Milestones 13.0–13.3 implement the Android/LAN device mesh within the scope below.
Human Gate 12 is **NOT_STARTED**. The user explicitly selected Android and asked
to finish Wave 12; this does not pass Gate 11 or Gate 12. Spatial audio remains
DEFERRED_MONO_CAPTURE. Final packaged verification receipts accompany this report.

## Delivered behavior

The desktop remains the sole authoritative runtime. An optional HTTPS listener
shares its existing model, databases and bounded speech lanes. It binds one
explicit RFC1918/loopback IPv4 address, stays off after every launch and requires
fresh desktop owner authorization to start, pair, approve, share or revoke.
There is no Internet relay, HTTP fallback, wildcard listener or automatic trust
installation. One-year CA/leaf certificates include strict-verification identifiers;
the CA private key is never stored and the leaf key password is protected by
Windows current-user DPAPI. Android CA trust is a manual user decision.

Five-minute single-use codes and P-256 key-possession proofs create pending
devices. The owner compares fingerprints and separately grants chat, optional
filename search and optional voice. Requests and core receipts use versioned,
signed envelopes, request/node correlation and bounded inputs. Canonical key
fingerprints prevent revoked keys being reused through alternative DER encodings.
Revocation rechecks run before result release and commits. Health/revocation
polls remain responsive while a long model turn is active. Damaged optional mesh
identity closes the mesh while preserving local desktop chat and the damaged data.

Android uses the bundled browser client with a nonextractable WebCrypto key and
pinned core public key in IndexedDB. Only key/identity metadata persists. Selected
session history and working state are kept in RAM; there is no offline transcript
cache, service worker, cloud script or offline command queue. Hiding the page or
clearing the screen stops capture/audio and clears private state. Late sync replies
cannot restore a cleared screen. Phone voice is push-to-talk, bounded to 55 seconds,
processed on the PC and always reviewed before Send. Read last reply speaks only
its first 240 characters. Mobile STT does not expose speaker templates/identities.

Existing sessions require explicit consent to share their entire retained history
and working state. New phone sessions are created at the core. CORE_ONLY/default
local memories and knowledge sources are filtered from remote model context;
replicated records retain audience/sensitivity restrictions. Secrets and action
approvals stay core-only. Sharing history also shares facts already written into
that history. The readonly search capability returns at most 30 relative filenames
from the PC's existing tool-sandbox; no file contents, other paths or writes.

Handoff assigns one primary interaction device and preserves session history and
working state. Active turns refuse handoff; desktop and mobile chat/new synthesis
check primary ownership. Clients stop stale playback when ownership changes.
An already-playing buffer can take up to five seconds to stop after remote handoff
or revocation: physical playback is not synchronously acknowledged across devices.
Stop audio on both devices before switching. Completed idempotent operations reuse
their original receipt; interrupted operations remain uncertain and cannot silently
redispatch. Audio/transcript results are volatile. Device journals cap at 2,000
operations; health/session reads do not consume the allowance.

## Verification scope

The final source checks passed 256 Python regressions (including 26 mesh cases),
10 frontend tests, 3 Rust tests, strict mypy across 86 modules, Ruff across 218
files, Rust formatting/Clippy and 22 scripted evaluations with zero critical
failures. The final PyInstaller/Tauri/NSIS build completed successfully.

The final frozen service passed 39 desktop transport checks and 20 mesh client
checks. Installation passed 5 upgrade checks, preserving 25 existing files;
the installed native host passed 16 lifecycle/IPC checks. The real Start Menu
shortcut points to the physical installed executable on this Windows Store host.

The installer and portable archive are in
`%USERPROFILE%\Documents\Codex\2026-10-05\s\outputs\adam-wave12`.
All 835 portable files match their final build sources byte for byte, and the ZIP
CRC check passed. SHA256SUMS.txt records both downloadable artifact hashes.

Real model verification initially hit the existing `RESOURCE.PRESSURE` RAM
guard on this busy PC. The diagnostic trace established that cause; the earlier
generic mesh error did not distinguish it. Resource policy was not relaxed and
unrelated apps were not terminated. The source-stage real Qwen/Whisper/Windows
speech run passed 21 checks; final installed verification is recorded separately
below. An initial frozen synthetic mesh run failed during packaging, then passed
on retry; its cause was not captured and is not asserted to be RAM pressure.

The final installed backend passed **22 real mobile-path checks**, using Qwen
chat, Whisper transcription and Windows speech through the shipped signed client
code with Node WebCrypto and trusted TLS. This is the same backend binary as the
final frozen build (verified during installation). The real frozen run was
blocked by RAM pressure; after build/packaging finished, the installed run passed
with the original resource guard. No claim of physical Android acceptance follows
from this emulated-client test.

Python security/edge tests cover owner elevation, code expiry/single-use, pending
and unpaired rejection, wrong signatures, packet schema/origin/HTTPS restrictions,
unshared sessions, explicit consent, command denial, scoped filename search,
idempotent duplicates, uncertain restart, in-flight revocation, alternative key
encoding, real memory/RAG filtering, damaged identity recovery and actual loopback
TLS trust/shutdown. The first TLS test caught missing certificate key identifiers;
the generator was fixed rather than relaxing verification.

The actual bundled JavaScript RPC code is exercised with real Node WebCrypto and
trusted TLS against disposable source/frozen/installed cores. DOM/IndexedDB are
test doubles in that harness, so it does not establish Android key persistence or
microphone behavior. Real Qwen, Whisper and Windows speech are exercised through
the same signed path. Model answers remain unverified despite verified transport.

The in-app browser inspected the live unpaired client at a 390×844 viewport
(375 CSS pixels after the scrollbar); no horizontal overflow and 47.2-pixel buttons.
A static, clearly labelled synthetic conversation/fingerprint fixture verified
the long fingerprint and chat layout at the same width. These screenshots do not
show a physical Android or a real paired browser session:

![Mobile pairing layout](evidence/wave12-mobile-pairing.jpg)

![Synthetic conversation layout](evidence/wave12-mobile-layout-fixture.jpg)

Final counts, installer/archive hashes and preservation checks are in
`evidence/wave12-*.json` and the delivery folder's SHA256SUMS.txt. Models and
personal/mesh data are excluded from the portable archive. Source checkpoint:
`8dcc4bf`. The network listener is left off after QA.

## Human handoff

Use [Android setup](mobile-mesh.md), then [Gate 12](gate-12.md) with your real phone
and trusted LAN. Certificate trust, physical microphone permission, phone browser
key persistence, screen-lock behavior, LAN/firewall behavior and acoustic playback
are pending human checks. Remote Internet mode is UNAVAILABLE. The earlier Gate 10
intermittent reply-to-PCM observation is not claimed fixed by this wave.
