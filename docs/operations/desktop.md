# ADAM desktop

The Windows desktop app adds chat, saved conversation history, memory search,
owner/demo switching, settings, developer diagnostics and an operational orb.
The existing terminal and API remain available. Local voice is available in the desktop.

Install the current-user Windows installer for the release you downloaded.
Launch ADAM Desktop from the Start menu. The app installs under
`%LOCALAPPDATA%/ADAM Desktop`, separately from `%LOCALAPPDATA%/ADAM` data and
model assets. The installer rejects a destination containing an existing ADAM store. No Python, Node or terminal is needed to run the
packaged app. Model weights, llama.cpp and E5 assets remain separate. Existing
supported public asset caches can be reused; personal data stays in its existing
directory. A fresh PC needs `scripts/setup-model.ps1` before model chat.
Missing models produce an offline state; memory commands remain usable.

On first launch, create an owner passphrase of at least 12 characters. An existing
installation uses its existing passphrase. Forgotten passphrases cannot be
recovered by the UI. Explore fictional demo uses a separate synthetic profile.
Lock the workspace before leaving the PC. Display preferences are the only data
saved in WebView local storage; conversation history lives in the backend store.
Local databases are cleartext under your Windows account.

Chat supports Enter to send and Shift+Enter for a new line. Select a saved
conversation to resume it. Stop response cancels the active stream; partial
answers are marked as stopped rather than represented as saved complete turns.
Use `/remember preference key = value` to save explicitly and `/forget key` to
forget. Memory search shows the record's provenance. Model answers remain
unverified. Developer mode requires fresh owner reauthentication and shows
operational metadata; it does not show hidden reasoning.

Settings can disable the avatar or reduce motion. The orb reflects actual
request/events/connection state, active microphone capture and spoken PCM energy.
Optional image reading requires explicit opt-in; see [vision.md](vision.md).
When a backend stops,
restart the local service from the visible recovery control and unlock again.
Restarting preserves committed history and memory.

Voice starts with the microphone off. Click Record voice, speak, then Finish
recording to review and send. Conversation mode is an explicit opt-in that sends
confident complete utterances after pauses. Read replies aloud is a separate
opt-in. Stop cancels audio and the current response. Voice settings select the
recognition language, speech engine and speech language; Reset pause style clears
the bounded in-memory pause adaptation. See [voice.md](voice.md) for asset setup,
English Windows speech versus multilingual Kokoro, privacy and known limits.
Speaker recognition is enabled in the compact configuration. Set up its public
models with `scripts/setup-speakers.ps1`; see [speakers.md](speakers.md) for
consent, fresh owner reauthentication, enrollment and transcript review.
Android connection controls are in the freshly unlocked Developer view.
Follow [mobile mesh setup](mobile-mesh.md) for trusted HTTPS, fingerprint approval,
explicit session sharing and handoff. The listener never starts automatically.

The native host launches only its bundled service and obtains a random loopback
port and private capability through a pipe. The UI receives neither that
capability nor the bearer token. Rust permits a fixed set of API routes, refuses
redirects/proxies, bounds requests/responses and correlates stream events.
Authentication transitions invalidate stale replies and cancel active streams.
The private service rejects browser origins even with its capability. First
launch setup is available only through this private desktop boundary.

Closing ADAM asks its owned service to shut down, then uses a Windows job object
to clean up owned descendants. It never kills an unrelated model server. An
occupied model port is refused rather than adopted. A second desktop instance
focuses the first. Window position/size persist through the Tauri window-state
plugin. Background mode is off at launch. An authenticated owner can explicitly
enable it when the tray is available; use the tray's Quit action to stop ADAM.

## Building

Run `scripts/build-desktop.ps1` from PowerShell after `scripts/dev.ps1 -Install`.
The script resolves the real Python environment, installs pinned build tools,
freezes the service, runs npm's lockfile install, builds Tauri and creates NSIS.
Stop the development Vite server before building; Windows locks its native
bundler DLL while it is running. Install Node, Rust, MSVC C++ build tools and a
Windows SDK. The build helper detects installed toolchains. Rust is under
`%LOCALAPPDATA%/ADAM/desktop-build`, with no global PATH changes.

The installer is unsigned. WebView2 is required; Tauri's installer bootstraps
it if absent, which requires internet. App operation after assets/setup is local.
See [Tauri Windows prerequisites](https://v2.tauri.app/start/prerequisites/) and
[Windows packaging](https://v2.tauri.app/distribute/windows-installer/).

`scripts/qa-desktop.py` tests the frozen service against disposable stores.
`scripts/desktop-browser-qa.py` starts a development-only synthetic UI fixture.
Its private capability stays in the Node proxy; the browser QA adapter is
excluded from production builds. This fixture is not a real model evaluation.

See [personal operations](personal-operations.md) for reminders and quiet hours.
