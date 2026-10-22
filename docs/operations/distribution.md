# Setup, updates and portable restore in ADAM 0.17.0 (Wave 17)

The desktop installer includes Python and runtime dependencies. It uses the
existing current-user Tauri/NSIS installation; no terminal Python setup is
required. Open **Setup and recovery** after creating/signing into the owner.
Hardware, data location and runtime checks are available there. Detection is an
offline observation, not a model benchmark or a guarantee of GPU compatibility.

## Initial model setup

Review the displayed RAM profile. The supported presets are the existing pinned
Qwen3 4B Q4 normal and abliterated models. Model setup uses SHA-256 verified
Hugging Face revisions and the pinned llama.cpp b11146 Vulkan Windows runtime.
Select a preset, reauthenticate and explicitly request its download/verification.
This starts a cancellable background job. Keep ADAM open and use Refresh checks
for status and downloaded MiB. Session revocation, hiding/leaving the view and
app shutdown cancel the work; the initial setup grant does not require repeated
reauthentication during a slow pinned download.
It installs a CPU profile with 2048 context and 512 output tokens; the current
owned runner uses three CPU threads. It does not start a model. Restart the
service afterwards. Existing verified downloads are reused. Failed partial
files are removed so retry starts cleanly; an active runtime is not replaced.

Allow about 3 GB for weights plus runtime and staging space. A 4B preset is
refused below 8 GiB system RAM, with reduced-mode guidance for a smaller
separately configured local server. More RAM may still be needed while other
apps run. The existing runtime resource guards remain in effect. The abliterated
preset has no output-quality or safety guarantee. No download occurs merely by
opening this page. Setup supports cancellation and clear checksum/I/O failures.

## Managed updates

Use an ADAM **managed release package** (`.adamrelease.zip`), not the ordinary
portable ZIP or installer. Obtain its SHA-256 independently from a trusted
release source. A checksum proves integrity, not publisher authenticity.
Paste the full local path, expected hash and stable/beta/dev channel. Verify
and stage it. Channel labels must match; downgrades use explicit rollback.
There is no automatic Internet update feed or background executable download.

Review the staged version, enter the owner passphrase again, then choose
**Approve activation and restart ADAM**. ADAM closes its owned service before
an offline helper can acquire the profile lease. The one-use approval is bound
to the owner session and expires in 60 seconds. Revocation or an open profile
blocks activation. The helper makes an encrypted pre-update snapshot with a
Windows current-user DPAPI-sealed key and retains the previous app/profile.

The helper restores a cloned profile, starts the candidate frozen service with
synthetic transport, lets startup migrations run, and checks recovery status,
release identity and health. It publishes one atomic active-generation pointer
only after these checks pass. Failed migrations leave the prior pointer and
profile active. This finite smoke test does not certify real model quality.
A damaged pointer is quarantined; the original installed app/profile can open
with a recovery note, and managed generations remain retained.

Explicit rollback validates the previous generation and returns to its
pre-update data. Newer changes remain in the newer generation and encrypted
snapshot; they do not appear in the rolled-back profile. Use the owner
passphrase valid in the restored profile. No live database or original model is
overwritten. Generations/snapshots are retained; there is no automatic pruning.

Use the installed **ADAM Desktop** Start Menu launcher or `Launch-ADAM.cmd` in
the portable folder so future launches follow the active managed generation.
Opening an individual generation's EXE directly bypasses that selection.
Updates to arbitrary third-party installers are unsupported; managed release
payloads contain the ADAM executable, config, backend and a checked manifest.

## Portable data

Enter a separate backup passphrase of at least 12 characters and create an
encrypted portable backup. The UI reports its file path and SHA-256. Copy that
file separately from the app package; keep the passphrase separately. Backup
contents include identity, owner credential verifier, conversations, memory,
knowledge blobs, task state, settings and reminders. Public weights, vector
indexes, phone/TLS keys, speaker biometrics and vault secrets are excluded.
Active tokens, approvals and running work are revoked/reset on restore.

On a fresh installation, create/sign into an owner, paste the backup path and
its passphrase, and stage restore into a fresh profile. Review and activate it
through the same offline handoff. Sign in with the restored owner's passphrase.
Use guided setup to select a compatible model. Re-pair phones in Devices,
re-enroll speakers, re-enter secrets, explicitly re-enable reminder delivery,
and use **Rebuild local knowledge indexes**. Reindexing runs in a worker thread;
knowledge sources are preserved independently of derived vectors and models.
Local update snapshots additionally retain same-PC model catalog, encrypted
vault, speaker/mesh databases and TLS settings. They are not cross-device exports.

The combined release is tested on this PC using disposable profiles and real
frozen services, including deliberate candidate-schema corruption and rollback.
Fresh Windows/VM installation, another physical hardware profile, Android
re-pairing and human comfort/acceptance remain pending in Gate 17.
