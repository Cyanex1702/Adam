# ADAM

A local-first, model-independent personal AI framework by **Cyanex**. ADAM keeps
identity, personal memory, knowledge, permissions and evaluation outside model
weights. The current combined implementation release is **0.20.0**.

## Run the complete offline source ZIP

1. Extract the entire **source-with-model** ZIP into a writable folder.
2. Double-click **RUN_ADAM.bat**. It runs the editable Python source.
3. Enter a message. Use `/quit` to exit and stop the owned model server.

**RUN_DEMO.bat** opens a separate fictional terminal profile. The BAT needs no
PowerShell execution-policy change, pip download or global Python installation.
The first launch verifies the model checksum before starting it.

```text
ADAM/
  RUN_ADAM.bat          # One-click source terminal
  RUN_DEMO.bat          # Fictional profile
  backend/adam/         # Editable runtime source
  apps/desktop/         # React/Tauri desktop source
  models/               # Verified Qwen3-4B Q4_K_M weights and model notices
  runtime/python/       # Relocatable Python and dependencies
  runtime/llama/        # Pinned local inference runtime
  data/                 # New private state, created on first use
```

The CPU profile uses three threads, 2048 context and 384 output tokens. Model,
source and private state are separate. The bundle contains the default chat model;
optional semantic-search, speech, speaker and visual models are separate assets.
The desktop installer/portable desktop app is also available as a separate build.

## Features

- Persistent conversations and policy-filtered memory with corrections, provenance,
  current/historical facts and forgetting.
- Local knowledge ingestion and cited retrieval, with keyword fallback when optional
  semantic assets are absent.
- Owner, guest and physically isolated fictional demo profiles.
- Reviewed tools/tasks, reminders, opt-in Internet integrations and explicit
  standard-Win32 See → Plan → Act → Verify actions.
- Evidence-linked personal relationships, timelines, goals, progress history and
  clearly labeled routine suggestions.
- Local model lifecycle/resource admission, encrypted backups, portable restore,
  staged updates, failed-migration rejection and rollback.
- Desktop, local voice and approved Android browser mesh implementations, with
  device setup and pending human acceptance documented separately.
- Sanitized portfolio demo and benchmark evidence with explicit measurement scope.
- Disabled-by-default synthetic behavior dataset and LoRA/QLoRA experiment workflow.
  **No validated fine-tuned adapter is included or active.**

Useful source-terminal commands:

```text
/remember preference editor = Example Studio
/correct editor = Another Editor
/show memory --history editor
/why know editor
/forget editor
/graph Cedar
/timeline Cedar
/goals
/briefing
```

## Develop from the GitHub source ZIP or a checkout

The GitHub source distribution excludes models, runtime binaries, personal data,
Git history and machine-specific operational evidence. It is not the complete
preconfigured offline ZIP described above.

Use Python 3.13 on Windows x64:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\scripts\setup-model.ps1
.\scripts\start.ps1
```

The existing PowerShell helpers manage the normal local development environment;
see [desktop setup](docs/operations/desktop.md) and the
[portable source guide](docs/operations/portfolio.md) for the distinct entry points.
For frontend development, run `npm ci` and `npm run dev` under `apps/desktop`;
normal production use requires the native desktop bridge.

## Validation and documentation

```powershell
python -m pytest -q
python -m ruff check backend tests
python -m mypy backend/adam
python -m adam.evals.runner --suite full --summary
```

The bundled benchmark identifies scripted framework probes explicitly. Its pass
rates do not claim general LLM quality, and missing VRAM/voice measurements remain
unavailable. Human validation is separate from automated verification.

- [Architecture](docs/public/ARCHITECTURE.md)
- [Threat model](docs/public/THREAT_MODEL.md)
- [Evaluation methodology](docs/public/EVALUATION.md)
- [Known limitations](docs/public/LIMITATIONS.md)
- [Personal intelligence](docs/operations/personal-intelligence.md)
- [Behavior training experiment](docs/operations/behavior-training.md)
- [Demo and delivery](docs/operations/portfolio.md)
- [Setup, update and restore](docs/operations/distribution.md)
- [Computer-action scope](docs/operations/computer-actions.md)
- [Voice](docs/operations/voice.md), [speakers](docs/operations/speakers.md),
  [Android setup](docs/operations/mobile-mesh.md)

## License

Copyright (c) 2026 **Cyanex**. ADAM is source-available under the supplied
[Community Non-Commercial License v1.0](LICENSE). Commercial use requires prior
written authorization or a separate commercial license. Read the contribution
terms before submitting changes. Third-party models and runtimes retain their own
licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).

Commercial licensing: **maliksaad277@email.com** · [Cyanex1702](https://github.com/Cyanex1702)
"# Adam" 
"# Adam" 
