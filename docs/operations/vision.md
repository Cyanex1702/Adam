# Vision in ADAM Desktop 0.15.0

The owner-only Vision view reads one supplied image or one explicitly selected
Windows application window. It starts off on every login and service restart.
Windows OCR reads text locally without downloading a model. General scene
interpretation requires a separately configured multimodal llama.cpp server.
Vision results are untrusted observations and never authorize actions.

## Use it

Open Vision, enter your owner passphrase, and select **Enable image reading**.
Choose one PNG, JPEG or WebP file, up to 3 MiB. Animated images, more than eight
million source pixels, or dimensions above 8192 are rejected. Orientation is
applied, metadata is removed, and images are resized to at most 2000 by 2000.
The result includes a thumbnail, extracted text, uncertainty and possible error
messages. These error candidates are text matches, not a verified diagnosis.

For a screenshot, open a harmless Notepad window. Enter the passphrase, select
**Arm and choose a window**, then select the listed window within 60 seconds.
Capture shows a topmost notice without taking focus, waits three seconds, and
reads that window once. Every attempt consumes the opt-in. Changed, minimized,
protected, oversized or unsupported windows fail closed. There is no desktop
capture fallback. Windows rendering runs in an isolated, bounded worker owned
by a kill-on-close job; cancellation discards its result and stops that worker.
The notice window is hidden afterwards and released when the service exits.

Default allowed application: `notepad.exe`. The owner may specify additional
executable basenames and private title substrings. Browsers, known credential
applications, ADAM, coding-assistant windows and sensitive title patterns are denied. These checks
and recognizable-secret filtering are heuristics, not comprehensive protection
against private content. Inspect the selected window before opting in.

**Disable and clear / cancel**, leaving the view, or hiding ADAM clears the
visible result and disables Vision. Authentication revocation invalidates
in-flight work. Raw images, OCR and window titles are held in RAM and omitted
from persistent audit events. RAM-only means no deliberate application storage;
it does not disable Windows paging or third-party process inspection.

## Optional visual model

Supply your own compatible multimodal llama.cpp server, image projector and
model ID. Only `http://127.0.0.1:PORT` is accepted. ADAM checks `/props` for
`modalities.vision: true` before transmitting an image to that local server.
It then uses `/v1/chat/completions` with a bounded image request and response.
Redirects, proxy environment settings and tool calls are not accepted. No model
is downloaded, started, or substituted for the existing text-chat model.

This release tests this adapter with fixtures; no visual model or scene-quality
claim is validated on this PC. Start with OCR on the i5/16 GB machine. Analysis
is denied below 512 MiB available RAM. A local server has its own memory needs
and retention policy; review its settings before sending private images.

Camera input, continuous monitoring, remote-device Vision, mouse/keyboard
actions, and ordinary chat image attachments are unavailable. The ordinary
chat identity reports no active visual input. Vision is a separate explicit
owner view. Human acceptance remains pending in Gate 15.

Provider references: [Microsoft OCR](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine),
[llama.cpp multimodal support](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md),
and [server API](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
