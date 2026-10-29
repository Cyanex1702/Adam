# Diagnostics and performance

**Diagnostics** is available from the desktop navigation before login, after
login, and when startup fails. It distinguishes the local service connection,
storage/configuration inspection, model lifecycle and measured resource admission.
Model loading runs after service readiness so a slow or unavailable model does not
block the owner login screen.

Checks refresh every five seconds while this panel is open. The model activity
display includes lifecycle-operation duration, active conversations and queued
requests. Reload and performance/device buttons wait for the model to become
idle. A chat sent during loading waits in a bounded, cancellable queue rather
than failing immediately with `MODEL.LIFECYCLE_BUSY`. A deliberate model change
during an active answer is still refused; finish or stop that answer first.
Owned model warmup has a 120-second elapsed deadline, including health requests.
A failed or cancelled warmup reaps the owned child; it cannot keep polling forever.

Use **Refresh checks** for current memory, disk and threshold readings. A service
failure produces a local fallback report with the preserved safe startup code.
**Copy safe report** excludes conversations, credentials, user filenames and paths;
custom model identifiers are hashed. It includes a hashed profile reference so
reports from different profiles can be distinguished. It does not upload anything.

There is one automatic reconnect attempt after repeated failed connection checks.
Persistent failure stops polling/restart attempts and keeps diagnostics accessible.
Manual reconnection remains available. Request timeouts are distinguished from a
lost service; a slow operation may still be running, so check its status before
retrying. Model loading can be retried without restarting the entire workspace.

## Performance modes

**CPU/GPU selection is separate from Eco/Priority.** In Diagnostics, **Use GPU ·
Vulkan** checks the runtime's first Vulkan adapter against measured GPU telemetry
and requires room for the weights plus a context allowance. All layers are then
requested on that GPU; discrete-GPU loading avoids retaining a host weight mapping.
The setting is saved only after the model loads successfully. A failed device
change preserves the saved selection and attempts one restoration of the previous
model. An interrupted change keeps the old saved selection for the next startup.
External servers must be configured in the application that manages them.

GPU acceleration still consumes some system RAM and is subject to the same RAM
and disk guards. Driver support, context size and other running apps affect whether
a model fits. Diagnostics reports the configured device; a live owned process and
GPU memory/activity provide separate evidence that it is actually running.

| | Eco | Priority |
| --- | --- | --- |
| Goal | Leave CPU time for other apps | Give ADAM's inference more CPU time |
| Inference threads | Up to 2 | Up to 6 |
| Logical / physical processing batch | 64 / 32 | 128 / 64 |
| CPU weight repacking | Disabled to save RAM | Enabled only if both layouts fit with headroom |
| Windows owned-process priority | Below normal | Above normal |
| Default RAM-use ceiling | 94% | 97% |
| Minimum free RAM | 512 MiB | 512 MiB |
| Minimum free data-drive space | 128 MiB | 128 MiB |

Thread counts also leave one logical core free where possible. Priority adds three
percentage points to the configured Eco RAM ceiling, capped at 97%; changing mode
does not change the configured free-RAM or free-disk minimums. Both modes reject
missing essential telemetry, and CPU model
loading checks a weight/context memory estimate before allocation. Actual runtime
failure remains possible; an estimate is not a capacity guarantee. Neither mode
closes, reprioritizes or edits another application's settings. Changing mode reloads
an active owned model; external local servers are not reconfigured.

## Common codes

| Code | Meaning / next action |
| --- | --- |
| `RESOURCE.RAM_PRESSURE` | Measured RAM is below the active policy; free memory or select a smaller model. |
| `RESOURCE.MODEL_RAM_BUDGET` | The selected CPU model exceeds the current weight/context estimate. |
| `MODEL.PORT_BUSY` | Another process uses the model port. Close the other model session or configure a distinct local origin. |
| `MODEL.CONTEXT_MISMATCH` | The running server offers less context than the selected profile requests. |
| `DESKTOP.PROFILE_IN_USE` | Another desktop service holds the profile lease; do not delete a live lock. |
| `MODEL.CONFIGURATION_INVALID` | Saved model metadata needs review; do not reset the whole profile. |
| `STORAGE.BUSY` | SQLite cannot obtain its read transaction yet. |
| `STORAGE.ACCESS_DENIED` | A permissions/opening failure, not a corruption verdict. |
| `STORAGE.WAL_INVALID` | The journal header failed validation; preserve the DB, WAL and SHM together. |
| `STORAGE.INTEGRITY_FAILED` | A database consistency check failed; use the local recovery guide with a verified copy. |

Valid committed SQLite WAL data is read through SQLite's read-only transaction
handling. ADAM does not discard journals or treat WAL presence alone as corruption.
SQLite may maintain its normal coordination metadata; original database pages and
WAL contents are not rewritten by inspection. Genuine failures remain read-only.

Source commands: `/help`, `/diagnostics`, `/performance eco`,
`/performance priority`, and `/reload`. `/careful on` enables a bounded second-pass
answer review; `/careful off` restores standard generation. Careful mode is slower,
keeps drafts out of the transcript, and does not certify correctness. Final
truncation still fails; it is never stored as a completed answer.

## Slow first replies and timeouts

`model.first_token_timeout_seconds` allows up to 300 seconds by default for a
first answer, including HTTP headers and prompt processing. Existing saved profiles
receive this default without changing their saved `timeout_seconds` value.
`model.timeout_seconds` is the idle allowance between answer fragments once text
starts (120 seconds in the compact profile). Heartbeats and hidden reasoning do
not count as answer progress. Stop cancels the connection in either phase.

The native desktop allows extra time for preparation and Careful mode, then uses
a 180-second visible-text idle watchdog instead of the old fixed five-minute
request cutoff. A 30-minute whole-request ceiling still applies. Timed-out or
cancelled partial answers are not saved as completed conversation turns.

Diagnostics includes both model timeout values. A longer wait does not create
RAM or improve model speed. Check resource readings and the selected performance
mode; a smaller approved model may be needed alongside other demanding software.

## Running and stopping ADAM

The desktop creates an **ADAM** tray icon while running. Its menu opens the
workspace or **quits ADAM and stops its owned model**. Settings has the same Quit
action. Closing the window quits by default. **Keep ADAM running in the
background** is an explicit owner choice for the current launch, resets on the
next launch, and requires a successfully created tray indicator. In that mode,
closing hides the window while scheduled work and inference stay available.
Opening ADAM again shows the existing window.

Hiding the desktop stops microphone recording and speech playback, discards pending
audio, and disables continuous conversation until explicitly enabled again. A
running model server itself does not capture microphone input. The visible chat
voice control indicates when recording is active.

Source/API-owned models have a separate Windows tray indicator with **Stop model
and free RAM**. The terminal remains the main interface. `/quit`, terminal close,
or a host crash releases ADAM's owned inference process through a Windows job.
ADAM never stops externally managed servers. Diagnostics reports process
ownership, PID, crash cleanup and source-indicator status without command lines
or file paths. Old extracted 0.20.0 copies must be updated to receive this fix.
