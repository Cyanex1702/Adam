# Human Gate 12 — Android and PC

Status: **NOT_STARTED**. Requires the user's Android phone and its explicit
certificate trust decision. Automated emulated-device/TLS QA is separate evidence.
The user's next-task instruction authorizes implementation while previous human
gates remain pending; it does not mark those gates passed.

Follow [mobile setup](mobile-mesh.md), then record Android version/browser, PC/LAN,
actual outcomes and any errors for each test:

- Trusted HTTPS opens without bypassing certificate warnings; listener is off
  after restarting the desktop and cannot bind public/wildcard interfaces.
- Unpaired/pending phone cannot chat/search/read history; fingerprint matches and
  desktop owner approval unlocks only selected capabilities.
- Text and reviewed microphone input use the same ADAM identity and PC model.
- Granted search finds a harmless PC tool-sandbox filename and reports the PC
  node; ungranted search, file contents and paths outside the sandbox stay denied.
- Explicit session sharing preserves its history and working state; unshared
  sessions and CORE_ONLY memories/sources stay unavailable.
- Desktop → phone → desktop handoff preserves the conversation. Stop audio
  before switching; active turns refuse handoff. Verify stale playback stops
  within the documented poll bound and never starts new synthesis on the old device.
- Disconnect PC/network, hide/lock phone and reconnect. Display clears, microphone
  stops, capabilities are honestly unavailable, no offline command is queued,
  committed history recovers and retries do not duplicate turns.
- Revoke phone during a request and while idle; no new result escapes the core,
  and phone display clears on the next poll. Old key stays denied after restart.
- Forget the revoked phone key, issue a new code and intentionally re-pair.
- Privileged commands and approvals remain on the authenticated desktop.
- Internet remote mode is UNAVAILABLE; skip Internet connectivity tests.

Do not mark HUMAN_VALIDATED until the PC and Android outcomes above are recorded.
