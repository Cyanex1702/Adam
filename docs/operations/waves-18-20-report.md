# Waves 18–20 — ADAM 0.20.0

The user authorized combined implementation on 2026-10-17, then requested a complete
source-with-model ZIP, one-click BAT, separate model folder and GitHub-ready source.
The supplied Community Non-Commercial License v1.0 is applied with Cyanex attribution.
Earlier pending human gates remain pending. Gate 18 and Gate 20 are NOT_STARTED.
The actual optional training experiment/Gate 19 is DEFERRED; no adapter is promoted.

Wave 18 adds explicit source-bound relationships, provenance inspection, valid-time
history/as-of queries, goals with revisions/progress history, manual briefings and
INFERRED repeated-activity suggestions. Graph entries never override current facts.
Existing memory policies apply before retrieval; correction/retraction invalidates
current links and forgetting cascades. Guest and remote access is denied; demo uses
a physically separate fictional profile. New source-terminal read commands are
`/graph`, `/timeline`, `/goals` and `/briefing`.

Wave 19 implements an owner-elevated, disabled-by-default dataset builder for
individually approved synthetic behavior examples. Credentials and known personal
memory overlap are rejected. Dataset content is explicitly reviewed; no automatic
conversation collection/upload occurs. The separate GPU LoRA/QLoRA recipe requires
a pinned model revision and dataset checksum, masks prompt tokens and records an
experiment without promotion. The comparison workflow rejects scripted/incomparable
reports, regressions and absent measured benefit. Actual GPU training and human
base-versus-adapter conversations have not been performed.

Wave 20 enriches fictional demo projects/goals/routines and adds a scoped note
write/verify/undo sandbox. The public benchmark dashboard derives category rates
from a freshly generated 22-case report and labels scripted transport, finite
rubrics and scenario-duration scope; unavailable VRAM/voice metrics remain null.
Public architecture, threat model, methodology, limits, contribution/security
guidance and Windows source CI are provided. Nothing is pushed or published.

Schema 7 adds persistent structures under the existing encrypted backup contract.
Known earlier schema prefixes remain readable; restore migrates them before health
verification. A schema-6 restore regression passes, new structures survive backup,
and restore resets training enablement. No schema-7 store is passed to an old binary
for rollback; managed generations retain their pre-update app/data pair.

Source checks passed: 463 Python tests, Ruff and strict mypy across 122 modules;
12 frontend tests, TypeScript/Vite production compilation; 22 scripted framework/
security evaluations with zero critical failures. All three Rust tests, including
the final route assertions, and Clippy pass. Frozen code matches all 122 source modules.
Browser QA verified demo isolation cues, source-linked relationships/timeline,
goal creation/completion, inferred routine labeling, measured dashboard scope and
safe note write/undo. The test found and fixed view headings and narrow-layout
overflow and a 95%-goal progress-button regression. Training UI checks covered
reauthentication, mandatory individual consent and disabled-by-default state.

Live API QA passes 48 checks against source and 48 against the frozen service.
Distribution QA passes 17 checks covering activation, failed-migration rejection,
rollback and encrypted model-free restore. A real 0.17 frozen-helper handoff passes
10 checks: schema-6 data migrates to 7 in a candidate clone while rollback retains
the original schema-6 store. Native lifecycle QA covers installed and portable
hosts, managed launch and preserving installer upgrade. Receipts are stored under
`docs/operations/evidence/waves18-20-*.json`.

The bundled Python and BAT were tested after relocating the source into a folder
with spaces. The actual pinned Qwen model starts on this machine's CPU, identifies
as ADAM, persists an explicit memory and unloads its owned server (six checks).
Normal BAT startup, `/status` and `/quit` were also exercised. The source-only ZIP
was extracted and its 50 new-feature tests passed in the locked development
environment. Final ZIP checks cover CRC, source manifests, license preservation,
model SHA-256 and exclusion of private state.

The full offline source bundle includes a copied CPython runtime and pinned
Qwen3-4B Q4_K_M in `models/`, with llama.cpp in `runtime/llama/`. RUN_ADAM.bat runs
editable source with a CPU profile; new personal state belongs in `data/`. The
GitHub source package excludes weights, binaries, private state, Git history and
machine-specific operational evidence. Model/runtime notices retain upstream terms.

Limits: no clean Windows VM, alternate PC, Android, live voice acceptance or human
long-term evaluation was performed in this release. GitHub CI is configured but
has not run remotely. No fine-tuned adapter was trained or promoted. These checks
do not close earlier human gates or Gates 18/20.
