# Project ADAM: first implementation report

Date: 2026-10-05. Source: `F:\Project Adam`. Version: 0.1.0.

Build Wave 1 — Conversational ADAM Alpha

- Implementation status: **AUTOMATED_VERIFIED**.
- Human validation status: **NOT_STARTED**.
- Milestones 0.1, 1.0, 1.1: **AUTOMATED_VERIFIED**.
- Wave 2 and all later waves: **NOT_STARTED**. Gate 1 must pass first.

## Start on this machine

From PowerShell:

```powershell
Set-Location -LiteralPath 'F:\Project Adam'
.\scripts\start.ps1
```

The Python environment, llama.cpp runtime, and two downloaded models are installed
under `%USERPROFILE%\AppData\Local\ADAM`. Startup needs no internet. `/new` resets the
RAM conversation, `/status` shows deterministic capabilities, `/quit` exits. The
helper stops a model process it owns on exit. Model/API processes used for verification
were stopped afterward; no inference server is intentionally left running.

`scripts/start.ps1 -Api` starts the HTTP/WebSocket gateway; documentation is at
http://127.0.0.1:8765/docs. `-Cpu` provides CPU fallback. The terminal is the user
interface for this wave. Full manual instructions are in `docs/operations/gate-1.md`.

## What was implemented

| Milestone | Delivered | Acceptance evidence |
|---|---|---|
| 0.1 | Python monorepo package, explicit desktop placeholder, typed IDs, event/error contracts, config precedence, feature flags, data resolver, SQLite migration framework, pytest/lint/type/eval scaffolding, ADRs | Seven initial tests; isolated editable install; config/default/env round trips; migration initialization and rollback; checkpoint 46cb5b2 |
| 1.0 | ModelProvider and llama.cpp adapter, registry metadata, config-based model selection, SSE text generation, RAM sessions, FastAPI chat, WebSocket events, CLI, model health, metadata-only traces | Streaming/session tests, Unicode transport, malformed/truncated/unavailable provider tests, cancellation/context failures, actual model generation; checkpoint c32a30f |
| 1.1 | Four versioned YAML identity files, personality/communication/epistemic rules, identity digest, deterministic capability description, seven epistemic statuses, unverified generated-answer metadata, actual-model golden scenarios | Model-independent identity checks, missing-pack failure, offline capability checks, real personality/abstention scenarios, terminal UTF-8 and cold startup |

Config defaults remain Qwen3-8B as the specification's reference. The compact user
profile selects Qwen3-4B-Instruct-2507 Q4_K_M, quantized by Unsloth. It uses 4096 context,
three CPU threads, one slot, bounded output, seeded sampling, and Vulkan GPU offload.
The Quadro M4000 was detected with 8192 MiB VRAM. Total GPU memory during model use
was about 4.3–4.5 GiB, including desktop use. A 4B model is a fit for framework testing,
not a guarantee of high reasoning or multilingual accuracy.

The requested abliterated/uncensored candidate was downloaded and tested. It fit in
memory, but failed multilingual stability (including a response-limit failure).
It remains available through `scripts/start.ps1 -Uncensored` and is explicitly not
the validated default. The normal model is the selected fallback the user authorized.
Model revisions/checksums and source links are in ADR 0004. Downloads were verified.

## Verification

- `scripts/check.ps1`: **26 tests PASS**, Ruff lint PASS, Ruff format PASS, strict mypy
  PASS (18 package source files). No model/network is required for these tests.
- Real normal-model scenario runner: **7/7 PASS** for plain knowledge response format,
  Roman Urdu/code switching format, ADAM identity, favorite food, unknown birthday,
  unavailable vision, and unavailable PC action. This is a simple smoke rubric, not
  a comprehensive factual, translation, or adversarial evaluation.
- Real two-turn conversation: the temporary name **River** was correctly recovered.
- Real coding stream returned `def square(n): return n ** 2`. Arithmetic smoke on the
  first candidate returned 391 for 17 × 23. These checks are not a mathematical benchmark.
- Live WebSocket streaming, real model shutdown -> DEGRADED/MODEL.UNAVAILABLE, and
  cold API startup were exercised. The terminal launcher cold-started, streamed a
  multilingual response, exited with code 0, and stopped its owned model process.
- Wheel build succeeded; bundled YAML files were inspected and loaded from a wheel
  installation rather than the source checkout. `pip check` found no broken requirements.
- PowerShell scripts parsed successfully. The development install is pinned through
  `requirements.lock.txt`. One non-failing Starlette/httpx deprecation warning remains
  in the test suite.

The initial live WebSocket sample measured about 3.4–3.9 seconds to first token and
4.3–8.1 seconds total for short coding/multilingual requests on the first candidate.
An earlier cold arithmetic turn took 19.18 seconds. These are individual observations,
not performance guarantees or benchmarks for the selected normal model.

## Files, dependencies, and schema

- `backend/adam/core`: configuration, IDs/contracts, migration runner, session/runtime.
- `backend/adam/models`: abstract provider, registry/card, llama.cpp transport adapter.
- `backend/adam/api`, `cli.py`: HTTP, WebSocket, and terminal entry points.
- `backend/adam/identity`, `evals`: packaged identity and real-model smoke runner.
- `tests`: foundation, runtime, identity, boundary, and provider failure tests.
- `scripts`: reproducible model setup, isolated environment, starter, check command.
- `docs/adr`, `docs/operations`: architecture decisions, interfaces, checkpoints,
  human gate instructions, evaluation evidence, and this report.
- Root configs, README, `.env.example`, Git ignore rules, pyproject, dependency lock;
  roadmap/execution tracker updated. Master architecture contracts were preserved.
- `apps/desktop/package.json`: an explicitly inert placeholder, not a desktop app.

Dependencies: FastAPI, Uvicorn, HTTPX, Pydantic, PyYAML; development tools pytest, Ruff,
mypy, and YAML typing stubs. llama.cpp b11146 is a separate native runtime. No LangGraph,
Tauri, Qdrant, voice runtime, tool package, or cloud service is added at this stage.

Schema 1 creates only runtime metadata and migration bookkeeping. No conversation,
memory, RAG, task, vault, or device tables exist. Migrations are transactional,
idempotent, checksum-checked, and reject unknown future versions. Traces contain IDs,
model metadata, status, safe error codes, and latency, not prompts/answers/reasoning.

Commands used: Python venv/pip install, pytest, Ruff, mypy, pip wheel/installation,
pip check, model downloads/SHA-256 checks, model launcher, scenario runner, local
HTTP/WebSocket and subprocess launcher checks, Git checkpoints. No remote repository
was created and no code was published.

## Known limitations and deferred work

- Model replies remain fallible. A terminal Roman Urdu sample incorrectly called
  Python lists unordered. Multilingual fluency and technical correctness need manual
  review; the substring scenario rubrics cannot detect all semantic errors. Generated
  responses are explicitly unverified. This observed weakness is disclosed for Gate 1.
- Sessions are RAM-only, retain a bounded recent window, and disappear on restart.
  Long context fails clearly instead of pretending summarization exists.
- Authentication/guest/demo privacy, persistent memory, RAG, tools, task orchestration,
  developer console, backup/restore, voice, avatar, desktop shell, browser/vision/PC
  control, mobile, hardware manager, and model promotion are deferred to their waves.
- Local API only; remote authentication is not implemented. No privileged action path
  exists. The model can give instructions, but cannot execute them.
- Default fallback model fits the detected GPU; latency and resource comfort still
  require the user's judgment. CPU fallback will be slower.
- Automatic approval review rejected cleanup of the abandoned ignored F: `.venv`
  and `.runtime` directories with the reason `blocked by policy`. They remain unused;
  active runtime/environment/data are on C:.

## Human validation record

Status: NOT_STARTED. Tester/date/issues/final decision: pending.

Use `docs/operations/gate-1.md` to test ordinary conversation, follow-up context,
coding, mathematics, streaming, multilingual behavior, identity/current model,
unavailable capabilities, fake human experiences, unknown personal facts, restart,
and intentional model shutdown. Include resource/latency comfort and the disclosed
multilingual weakness in the decision.

Report Gate 1 PASS or reproduction details for issues. Per execution-plan sections
3.4 and 7, implementation stops here until this wave is human validated.
