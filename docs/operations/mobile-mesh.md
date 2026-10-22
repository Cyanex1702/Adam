# Android mobile connection

Wave 12 adds an Android browser client. Your PC stays the authoritative core;
it runs the model, speech processing and read-only filename search. No Android
app download or model on the phone is required. Remote Internet access is not
implemented. The listener is OFF after every app launch, even when configured.

## Prepare trusted HTTPS

1. Connect the PC and Android phone to the same trusted home LAN. Find the PC's
   IPv4 address with `ipconfig`, for example `192.168.1.20`. Use the actual address;
   `0.0.0.0`, public Internet addresses and IPv6 are refused.
2. Close ADAM Desktop, open PowerShell in `%PROJECT_ROOT%`,
   then run `scripts/setup-mesh.ps1 -Address 192.168.1.20` with your actual address.
   The script uses the development Python environment and prepares TLS material
   in the same `%LOCALAPPDATA%\ADAM` data directory as the desktop. If you use
   `ADAM_DATA_DIR` or another Windows account, supply that directory with `-DataDir`.
   Never point it at a different private store to bypass a setup error.
3. Transfer **only** `mesh\tls\ca.crt` from that data directory to your phone,
   using a trusted cable or other trusted transfer. The desktop also shows its
   certificate path. Do not transfer the registry, encrypted key, password file,
   databases or model files.
4. On Android, install this certificate as a user CA through Settings. The exact
   menu depends on the phone; search Settings for “Install certificate” and choose
   the CA option. This is an explicit trust decision on your phone. The setup
   script never installs trust certificates or changes firewall rules. Remove
   this CA when you stop using the mesh. Its CA private key was never saved.
5. Open ADAM Desktop, sign in, then unlock Developer mode with your owner
   passphrase. In Android connection press Start listener. If Windows requests
   firewall access, restrict it to the trusted private network; avoid public
   networks. Open the displayed `https://PC-IP:9443` URL in Android Chrome.
   **Stop if Chrome shows a certificate warning.** Correct the CA/address/date
   rather than bypassing the warning. WebCrypto and microphone access need a
   trusted secure context. No HTTP fallback is available.

If the PC address changes or the one-year certificate expires, stop the listener,
remove the old CA from the phone, archive the old `mesh/tls` configuration locally,
and explicitly generate and trust a new certificate for the correct address.
Setup refuses to overwrite existing TLS material. Reserve the PC's address in
your router if useful. Pairing keys are separate from the TLS certificate.

## Pair and use

Create a five-minute pairing code on the desktop. Enter it and a device label on
the phone. Compare the **entire** fingerprint shown on both screens, then approve
that device on the desktop. Search and speech are separate optional grants;
neither is enabled by default. A pending device has no chat, history or search
access. No owner passphrase is entered on the phone.

Press Reconnect / sync after approval. New phone session creates a session on
the PC and assigns this phone as its primary interaction device. For an existing
desktop session, select it on the PC, explicitly consent to sharing **its entire
retained history and working task state**, then hand it to the phone. Reconnect
and select its ID on the phone. Hand it back with Return to PC; select its ID on
the desktop to refresh history. Stop audio on both devices before handoff.
Active model turns refuse handoff. Chat and new synthesis enforce primary
ownership, and clients poll ownership to stop stale playback. An already-playing
buffer can take up to five seconds to stop after a remote handoff or revoke;
physical audio is not synchronously acknowledged across the network.

Send text, or Record voice → Finish recording → review the transcript → Send.
Recording is push-to-talk only, bounded to 55 seconds. Phone speech is decoded
on the PC; it never authenticates speakers, auto-sends or grants privileges.
Read last reply speaks its first 240 characters using the PC's configured local
engine. Windows English output remains the compact default; Urdu recognition
can be selected in future UI extensions but the initial phone UI uses auto
language. Headphones avoid playback entering the microphone.

Search returns at most 30 relative filenames from the PC's `tool-sandbox` under
the active data directory. It cannot read file contents, choose another path,
write files, run commands or approve desktop tools. Place a harmless filename
fixture there to test. Receipts identify the executing PC node. Model prose is
always marked unverified, independently of a verified protocol signature.

## Privacy, offline and recovery

Only device key material, the device/node ID and pinned core public key persist
in Android IndexedDB. The private signing key is nonextractable. There is no
transcript, task-state or audio cache, service worker, cloud relay, offline send
queue or third-party script. Reload/reconnect pulls explicitly shared sessions
from the PC. Screen hiding, screen clearing and detected disconnection clear
the in-memory conversation and stop the microphone/audio. This does not protect
an already unlocked phone; use Android's screen lock and revoke lost devices.

CORE_ONLY/default local memories and knowledge sources are excluded from remote
model context; only explicitly replicated records can enter it, subject to the
existing audience and sensitivity checks. Secrets and approvals remain core-only.
Sharing a conversation also shares facts previously written into that conversation;
review it before consenting. Revocation removes all grants and rejects requests
and cached receipts immediately at the core; clients clear the display on the
next poll/request. A revoked key cannot be reused. Intentionally re-pair by
forgetting the old key on the phone and creating a new code after desktop revocation.

Retries keep the same request ID. Completed operations return their original
signed receipt; ambiguous interrupted operations return RESULT_UNCERTAIN and
are never dispatched twice. Audio is volatile: repeating its completed ID cannot
retrieve an audio/transcript cache. The persistent journal caps at 2,000 operations
per device; status and session reads do not consume that allowance. Revoke and
re-pair intentionally if REQUEST_LIMIT is reached. Request signatures expire
after 60 seconds; align the PC and phone clocks if REQUEST_EXPIRED appears.
No remote listen mode starts automatically after a core restart.

If MESH.IDENTITY_UNAVAILABLE appears, the mesh fails closed while local desktop
chat stays available. Close ADAM, preserve the entire damaged `mesh` directory
in a local backup, then recover its registry/key under the original Windows
account or explicitly archive it and prepare a new identity/TLS configuration.
Existing phones must forget their old keys and re-pair. The app never silently
replaces the registry or regenerates a damaged identity.

Device/TLS keys are local account-bound and excluded from portable backups.
Re-pair after relocating/restoring the authoritative core. The installer upgrades
the app without replacing existing mesh data. Human Android/LAN testing is tracked
in [Gate 12](gate-12.md); automated loopback/TLS tests cannot pass that gate.

Protocol references: [WebCrypto ECDSA signing](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto/sign),
[CryptoKey persistence](https://developer.mozilla.org/en-US/docs/Web/API/CryptoKey),
[cryptography EC signatures](https://cryptography.io/en/stable/hazmat/primitives/asymmetric/ec/).
