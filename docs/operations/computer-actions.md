# Computer actions in ADAM 0.17.0 (Wave 16)

Open **Computer actions** as the owner. Enter your passphrase, specify exact
allowed executable filenames (default `notepad.exe`), then enable and list
windows. Choose **Observe**. The capture notice is visible before any image is
read. Observation supplies a thumbnail, OCR text and supported native controls;
none of this content grants permission or is interpreted as instructions.

Choose an exact control and add up to eight steps. Text replacement must verify
the same field against the exact replacement. A button click must name a
separate observed result control and an exact changed result. Preview the plan,
optionally dry-run it without input, then enter the owner passphrase again and
approve the exact plan. Approval is once-only and expires after 30 seconds;
observations expire after 60 seconds. An expired observation requires re-observation.

The provider supports standard Win32 Edit/RichEdit fields and push buttons.
Modern custom-drawn interfaces, browser controls, arbitrary screen coordinates,
mouse movement, global keystrokes, shell windows and password controls are
unavailable. Duplicate actionable labels are denied. Known sensitive titles,
applications and action labels are denied even if included in an app allowlist.
These heuristics cannot prove an arbitrary application is harmless. Use only
applications whose effects you understand. Every action requires explicit review.

Before acting, ADAM rechecks window identity, controls and the screenshot. It
then verifies expected control text and captures the post-action screen after
each step. Unexpected changes stop remaining steps. VERIFIED means the stated
native UI result was observed; it does not independently prove an external
account, file or network effect. Perception is never action permission, and
ordinary chat has no computer-action tools.

Disable/cancel, hiding ADAM or leaving this view invalidates remaining work.
A dispatched action cannot be recalled. Failure after dispatch is uncertain;
inspect the target before trying anything else. To recover editable text, make
a fresh replacement plan with the previous value and review it normally.
Clicks have no automatic undo. Screenshots, OCR and plan payloads remain in RAM;
audit events store only status metadata. Windows paging is outside this policy.

Automated QA uses a disposable native application with independent checks of its
actual fields and button result. Human acceptance remains pending in Gate 16.
