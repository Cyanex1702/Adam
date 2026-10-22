# PROJECT ADAM — IMPLEMENTATION ROADMAP

**Document:** `PROJECT_ADAM_ROADMAP.md`\
**Architecture dependency:** `PROJECT_ADAM_MASTER_SPEC.md`\
**Roadmap baseline:** v0.1\
**Rule:** Each milestone implements only its declared scope. Future architecture may be represented by interfaces/contracts, but future feature behavior must not be prematurely implemented.

---

# Roadmap Principles

1. **Contract before feature.**
2. **Tests before expansion.**
3. **No silent scope creep.**
4. **No model-specific business logic in ADAM core.**
5. **Security boundaries exist before risky tools.**
6. **Every milestone leaves the repository runnable.**
7. **Every milestone has acceptance criteria.**
8. **A failed release gate blocks the next milestone until resolved.**
9. **Derived indexes are rebuildable.**
10. **Data migrations are explicit.**

---

# Phase 0 — Architecture Freeze

## Milestone 0.1 — Repository and Contract Foundation

**Implementation status (2026-10-05):** `AUTOMATED_VERIFIED`. Checkpoint: `46cb5b2`.

### Goal
Create the canonical repository skeleton and formal domain contracts without building future features.

### Implement
- monorepo foundation,
- backend Python package,
- desktop placeholder package,
- configuration loader,
- feature-flag system,
- canonical event envelope,
- canonical structured error envelope,
- typed domain IDs,
- version constants,
- initial migration framework,
- pytest setup,
- scenario-eval runner skeleton,
- architecture decision record directory,
- lint/type/test commands,
- `.env.example` containing no real secrets,
- local data-directory resolver.

### Do not implement
- voice,
- RAG,
- agent tools,
- mobile,
- avatar,
- browser automation.

### Acceptance
- clean install succeeds,
- test command passes,
- config loads from defaults + environment + user config,
- event and error schemas serialize/deserialize,
- data directory resolves correctly,
- migration runner can initialize an empty DB,
- repository has one-command dev startup documentation.

---

# Phase 1 — ADAM Core Runtime

## Milestone 1.0 — Local Text Brain

**Implementation status (2026-10-05):** `AUTOMATED_VERIFIED`. Checkpoint: `c32a30f`.

### Goal
A text-only local ADAM that can converse through a replaceable model interface.

### Implement
- `ModelProvider` contract,
- `LlamaCppProvider`,
- model registry basic metadata,
- Qwen3-8B initial local configuration,
- streaming text generation,
- session manager,
- FastAPI text endpoint,
- WebSocket token streaming,
- minimal CLI or dev chat UI,
- model health check,
- structured trace per conversation turn.

### Acceptance
- ADAM starts fully offline,
- model can be swapped through config without changing chat code,
- text streaming works,
- provider failure returns structured degraded/error state,
- model metadata appears in trace,
- no model-specific prompt formatting leaks into domain services.

---

## Milestone 1.1 — Identity Pack and Epistemic Rules

**Implementation status (2026-10-05):** `AUTOMATED_VERIFIED`. Human Gate 1: `HUMAN_VALIDATED` (user acceptance in chat, 2026-10-05).
See `docs/operations/wave-1-report.md` and the final milestone checkpoint in Git.

### Goal
ADAM remains ADAM independently of model behavior.

### Implement
- Identity Pack loader/versioning,
- personality/communication config,
- epistemic status enum,
- fake-embodiment rules,
- system/capability self-description interface,
- response metadata for known/retrieved/inferred/unknown where applicable,
- golden personality scenarios.

### Acceptance
- model swap preserves identity tests,
- "favorite food" scenario does not fabricate eating experience,
- unavailable capability questions produce accurate answers,
- unknown personal facts are not invented in test suite.

---

# Phase 2 — Persistence and Memory

## Milestone 2.0 — Conversation Persistence

**Implementation status (2026-10-05):** `AUTOMATED_VERIFIED`. See docs/operations/milestone-2.0.md.

### Implement
- SQLite session schema,
- conversation messages,
- timestamps,
- session summaries placeholder,
- trace references,
- schema migrations,
- transactional writes.

### Acceptance
- sessions survive restart,
- DB rollback works on simulated failed write,
- historical conversations are queryable,
- no raw secrets are persisted.

---

## Milestone 2.1 — Working Memory

**Implementation status (2026-10-05):** `AUTOMATED_VERIFIED`. See docs/operations/milestone-2.1.md.

### Implement
- recent-turn context,
- active task/context fields,
- rolling summary,
- context-budget manager v1,
- stale tool/result pruning interface,
- token estimation abstraction.

### Acceptance
- long chats do not blindly resend entire history,
- current instructions survive summarization tests,
- context budget is observable.

---

## Milestone 2.2 — Long-Term Memory v1

**Implementation status (2026-10-05):** `AUTOMATED_VERIFIED`. See docs/operations/milestone-2.2.md.

### Implement
- memory schema,
- semantic / episodic / preference / project / goal types,
- provenance,
- confidence,
- importance,
- privacy field,
- temporal validity,
- pinned memories,
- memory search,
- explicit "remember / correct / forget / show memory / why know" commands.

### Acceptance
- current vs historical preference tests pass,
- unknown preference test abstains,
- correction updates temporal state rather than silently duplicating,
- pinned memory cannot be auto-expired,
- provenance is shown on request.

---

## Milestone 2.3 — Memory Consolidation and Archive

**Implementation status (2026-10-05):** `AUTOMATED_VERIFIED`. Human Gate 2: `HUMAN_VALIDATED` (user authorized Wave 3, 2026-10-05). See docs/operations/wave-2-report.md.

### Implement
- deduplication,
- summary memories,
- hot/warm/cold state,
- archive rules,
- importance decay separate from deletion,
- memory candidate inspector,
- background consolidation task.

### Acceptance
- duplicate preference examples merge correctly,
- old meaningful memory remains searchable,
- low-value archival memories stop polluting normal retrieval,
- consolidation is idempotent.

---

# Phase 3 — Knowledge and RAG

## Milestone 3.0 — Knowledge Ingestion

**Implementation status (2026-10-05):** `AUTOMATED_VERIFIED`. 49 regression tests, Ruff and strict mypy pass. Original blobs, versioned chunks and permission-scoped canonical identities retained.

### Implement
- file source registry,
- parsers for common text/Markdown/PDF/code inputs,
- source metadata,
- content hashing,
- deduplication,
- chunking interfaces,
- project namespaces,
- file change detection foundation.

### Acceptance
- duplicate files do not create duplicate canonical sources,
- source move/rename can be detected without losing identity,
- permissions metadata accompanies source records.

---

## Milestone 3.1 — Local Vector Retrieval

**Implementation status (2026-10-05):** `AUTOMATED_VERIFIED`. 51 regression tests pass; real pinned E5/Qdrant evaluation achieves recall@5 10/10 against a predeclared 90% target on 20 synthetic sources. See docs/operations/evidence/wave3-retrieval.json.

### Implement
- Qdrant local integration,
- embedding provider interface,
- local embedding model,
- vector index,
- keyword search,
- hybrid retrieval v1,
- evidence context builder,
- source citations.

### Acceptance
- known RAG test set meets baseline retrieval target,
- citations reference real sources,
- unauthorized source does not enter context,
- deleting/reindexing derived vectors does not lose source data.

---

## Milestone 3.2 — Reranking and Grounded Answers

**Implementation status (2026-10-05):** `AUTOMATED_VERIFIED`. 56 regression tests and static checks pass; real grounding evaluation 19/19, live API 25 assertions, terminal 8 checks and prior Qwen smoke 7/7. Human Gate 3: `HUMAN_VALIDATED` (user requested the next task after startup repair). Extractive answer policy and limits documented in docs/operations/wave-3-report.md.

### Implement
- reranker interface,
- evidence sufficiency check,
- grounded answer policy,
- retrieval inspector,
- unsupported-claim evaluation.

### Acceptance
- answer-unavailable scenarios abstain,
- conflicting documents are surfaced as conflict,
- source attribution remains accurate.

---

# Phase 4 — Privacy, Authentication, and Demo Isolation

## Milestone 4.0 — Policy Engine

**Implementation status:** `AUTOMATED_VERIFIED`. 60 regression tests and static checks pass. Deterministic policy filters memory and knowledge before model context; legacy owner source hashes remain stable.

### Implement
- sensitivity classes,
- audience ACL,
- disclosure owner,
- subject/source actor,
- policy decision object,
- deterministic context filter.

### Acceptance
- guest cannot retrieve owner-private memory,
- filtered private memory never reaches model input in tests,
- policy denial has explainable reason code.

---

## Milestone 4.1 — Owner / Guest / Demo Modes

**Implementation status:** `AUTOMATED_VERIFIED`. 63 regression tests and static checks pass. Authenticated owner API sessions, physically separate guest/demo profiles, guarded mode switches and developer reauthentication are implemented.

### Implement
- session role handling,
- owner session,
- guest session,
- demo data namespace,
- developer mode auth gate,
- mode indicator.

### Acceptance
- demo mode has zero access to owner namespace,
- mode switch requires correct authorization,
- demo test suite can be given to another user safely.

---

## Milestone 4.2 — Secrets Vault Foundation

**Implementation status:** `AUTOMATED_VERIFIED`. 70 regression tests and static checks pass. Windows DPAPI, encrypted password fallback, scoped backend consumers, handles, redaction and NEVER_LOG enforcement are implemented.

### Implement
- vault interface,
- OS secure-storage adapter where practical,
- encrypted fallback vault,
- secret handles,
- redaction rules,
- NEVER_LOG enforcement.

### Acceptance
- secret values never appear in normal logs/traces,
- tool can obtain a secret through handle without model seeing raw value,
- vault unavailable produces safe failure.

---

# Phase 5 — Tool Runtime and Safe Actions

## Milestone 5.0 — Tool Registry

**Implementation status (2026-10-06):** `AUTOMATED_VERIFIED`. See docs/operations/milestone-5.0.md.

### Implement
- tool schema,
- risk levels,
- scope requirements,
- reversibility metadata,
- tool capability registry,
- tool request/result envelopes.

### Initial tools
- system info,
- search files,
- read allowed file,
- open file,
- open application,
- create note,
- search memory,
- search knowledge.

### Acceptance
- tools are discoverable through registry,
- invalid args rejected deterministically,
- risk/scope metadata required for every tool.

---

## Milestone 5.1 — Permissioned Tool Execution

**Implementation status (2026-10-06):** `AUTOMATED_VERIFIED`. See docs/operations/milestone-5.1.md.

### Implement
- policy check before execution,
- filesystem scopes,
- approval requirement,
- trace/action IDs,
- tool result verification.

### Acceptance
- unauthorized write is blocked outside LLM,
- read-only action cannot mutate state,
- failed action cannot be reported as completed.

---

## Milestone 5.2 — Dry Run, Undo, and Action Journal

**Implementation status (2026-10-06):** `AUTOMATED_VERIFIED`. See docs/operations/milestone-5.2.md.

### Implement
- action journal,
- reversible file move,
- recycle-bin/quarantine abstraction,
- snapshot-before-edit interface,
- dry-run plan output.

### Acceptance
- "clean downloads" sandbox scenario performs zero changes before approval,
- undo restores supported file operation,
- audit history shows before/after/result.

---

# Phase 6 — Task Orchestration

## Milestone 6.0 — Structured Task Engine

**Implementation status (2026-10-06):** `AUTOMATED_VERIFIED`. See docs/operations/milestone-6.0.md.

### Implement
- task and step schemas,
- dependencies,
- task state machine,
- priorities,
- persistent checkpoints,
- cancellation.

### Acceptance
- task resumes after process restart,
- dependency graph prevents premature step,
- cancelled task stops safely.

---

## Milestone 6.1 — Planner / Executor / Verifier

**Implementation status (2026-10-06):** `AUTOMATED_VERIFIED`. See docs/operations/milestone-6.1.md.

### Implement
- task classifier,
- fast/direct route,
- structured planner,
- executor,
- verifier,
- expected-result contracts.

### Acceptance
- "diagnose but do not modify" test never writes,
- "fix and test" requires verification before completion,
- plan is structured, inspectable, and traceable.

---

## Milestone 6.2 — Replanning and Idempotency

**Implementation status (2026-10-06):** `AUTOMATED_VERIFIED`. ADAM 0.5.0 passes 103 regressions, static checks and 33 live PC checks. See docs/operations/milestone-6.2.md and gate-5.md. Gate 5 human validation remains pending.

### Implement
- retry/replan budgets,
- in-flight action state,
- action idempotency key,
- recovery of uncertain task state,
- conflict/resource locks.

### Acceptance
- simulated crash after external action does not duplicate action,
- failed step triggers bounded replan,
- infinite-retry scenario terminates with explicit failure.

---

# Phase 7 — Observability and Evaluation

## Milestone 7.0 — Developer Trace Console

**Status:** AUTOMATED_VERIFIED, 2026-10-06; Gate 6 human validation pending. See `docs/operations/wave-6-report.md`.

### Implement
- trace store,
- event timeline,
- model metadata,
- latency breakdown,
- tool trace,
- task graph view data,
- memory/RAG inspector APIs,
- health dashboard API.

### Acceptance
- one request can be traced end-to-end,
- sensitive fields are redacted by policy,
- trace contains decisions/evidence/results, not hidden reasoning.

---

## Milestone 7.1 — Evaluation Harness v1

**Status:** AUTOMATED_VERIFIED, 2026-10-06; Gate 6 human validation pending. See `docs/operations/wave-6-report.md`.

### Implement
- golden conversation runner,
- memory scenarios,
- RAG benchmark,
- tool selection scenarios,
- privacy scenarios,
- hallucination/abstention scenarios,
- model comparison report.

### Acceptance
- one command runs full local eval suite,
- failures produce machine-readable report,
- baseline scores stored per release/model.

---

## Milestone 7.2 — Security / Red-Team Suite

**Status:** AUTOMATED_VERIFIED, 2026-10-06; Gate 6 human validation pending. See `docs/operations/wave-6-report.md`.

### Implement
- prompt injection fixtures,
- malicious document fixtures,
- role impersonation,
- memory poisoning,
- scope escalation,
- encoded exfiltration,
- malformed tool call scenarios.

### Acceptance
- critical privacy/security tests are zero-tolerance release gates,
- injection source cannot change tool authorization.

---

# Phase 8 — Persistence, Backup, and Recovery

## Milestone 8.0 — Snapshot and Backup

**Implementation status:** `AUTOMATED_VERIFIED` on 2026-10-06; Gate 7 human validation pending.
Evidence: `docs/operations/milestone-8.0.md`, `docs/operations/wave-7-report.md`.

### Implement
- snapshot interface,
- encrypted backup format,
- checksums,
- retention generations,
- backup manifest.

### Acceptance
- backup can be created while ADAM remains consistent,
- checksum validation catches corrupted archive,
- vault can be excluded or backed up separately.

---

## Milestone 8.1 — Restore and Recovery Mode

**Implementation status:** `AUTOMATED_VERIFIED` on 2026-10-06; Gate 7 human validation pending.
Evidence: `docs/operations/milestone-8.1.md`, `docs/operations/wave-7-report.md`.

### Implement
- fresh-install restore,
- recovery/read-only mode,
- rebuild derived indexes,
- restore verification suite.

### Acceptance
- clean environment restores identity + memory + settings,
- derived vector store can be rebuilt,
- recovery works without original LLM installed.

---

## Milestone 8.2 — Human Data Export

**Implementation status:** `AUTOMATED_VERIFIED` on 2026-10-06; Gate 7 human validation pending.
Evidence: `docs/operations/milestone-8.2.md`, `docs/operations/wave-7-report.md`.

### Implement
- JSON/JSONL export,
- project/person/date filters,
- Markdown summaries,
- purge semantics documentation.

### Acceptance
- exported records preserve provenance and timestamps,
- export never includes secret values by default.

---

# Phase 9 — Hardware / Model Intelligence

## Milestone 9.0 — Hardware Profiler

**Status:** `AUTOMATED_VERIFIED` on 2026-10-07. Offline observation, bounded sensor fallbacks and local CPU hashing; 155 regressions passed at its checkpoint.
Evidence: `docs/operations/milestone-9.0.md`, `docs/operations/wave-8-report.md`.

### Implement
- CPU/RAM/GPU/VRAM/storage/OS detection,
- runtime availability,
- compute profile,
- basic local benchmark.

### Acceptance
- profile accurately describes current machine,
- unknown hardware degrades gracefully,
- profiler never requires internet.

---

## Milestone 9.1 — Resource Manager

**Status:** `AUTOMATED_VERIFIED` on 2026-10-07. Shared admission, lifecycle, priority scheduling and explicit OOM recovery; 166 regressions passed at its checkpoint.
Evidence: `docs/operations/milestone-9.1.md`, `docs/operations/wave-8-report.md`.

### Implement
- resource telemetry,
- model lifecycle states,
- priority scheduler hooks,
- VRAM/RAM pressure handling,
- low-resource/degraded mode.

### Acceptance
- background workload yields to interactive workload,
- resource pressure is visible in health dashboard,
- OOM scenario triggers safe recovery rather than crash loop.

---

## Milestone 9.2 — Model Benchmark and Migration

**Status:** `AUTOMATED_VERIFIED` on 2026-10-07. Gated trial/finalize/rollback with real Vulkan/E5 evidence; 186 final regressions, 38 live and 9 browser checks passed.
Evidence: `docs/operations/milestone-9.2.md`, `docs/operations/wave-8-report.md`.

### Implement
- candidate-model benchmark runner,
- ADAM capability scorecard,
- provider/model promotion workflow,
- rollback.

### Acceptance
- candidate cannot become default without required gates,
- identity/memory survive model swap,
- old model remains selectable until promotion finalized.

---

# Phase 10 — Desktop Product Shell and Avatar

## Milestone 10.0 — Tauri Desktop Application

**Status:** `AUTOMATED_VERIFIED` on 2026-10-07; see `docs/operations/milestone-10.0.md`. Gate 9 human validation pending.

### Implement
- production desktop shell,
- chat interface,
- session list,
- owner/demo mode selector,
- settings,
- developer console entry,
- backend lifecycle management.

### Acceptance
- user can install/start ADAM without manual terminal orchestration,
- backend crash is surfaced and recoverable.

---

## Milestone 10.1 — Abstract Avatar

**Status:** `AUTOMATED_VERIFIED` on 2026-10-07; see `docs/operations/milestone-10.1.md`. Native sustained frame rate and UX remain Human Gate 9 checks.

### Implement
- shader/orb avatar,
- event-driven state machine,
- idle/thinking/searching/tool/error/offline states,
- feature flags.

### Acceptance
- avatar state is driven by events, never direct agent imports,
- UI maintains target frame rate on target PC.

---

# Phase 11 — Voice Foundation

## Milestone 11.0 — Push-to-Talk Voice

**Status:** `AUTOMATED_VERIFIED` in 0.10.0 on 2026-10-08, including frozen speech providers.
See `docs/operations/milestone-11.0.md`. Real microphone acceptance remains Gate 10.

### Implement
- audio capture,
- noise-processing adapter,
- VAD,
- faster-whisper STT provider,
- transcript confidence,
- Kokoro TTS provider,
- push-to-talk workflow,
- text fallback.

### Acceptance
- clean-room voice conversation works locally,
- low-confidence transcript is surfaced,
- raw audio retention follows configured policy.

---

## Milestone 11.1 — Turn-Taking Engine

**Status:** `AUTOMATED_VERIFIED` profile-scoped heuristics in 0.10.0.
See `docs/operations/milestone-11.1.md`. Biometric per-speaker attribution awaits
Wave 11; real acoustic false-turn rate remains Gate 10.

### Implement
- pause-duration features,
- linguistic completeness,
- turn-end probability,
- per-speaker pause profile,
- wait/take-turn state machine.

### Acceptance
- scripted long-pause scenarios meet false-interruption target,
- incomplete sentence waits longer than complete sentence,
- adaptation is bounded and reversible.

---

## Milestone 11.2 — Barge-In and Streaming Voice

**Status:** `AUTOMATED_VERIFIED` rolling partial STT, chunked TTS and cancellation in 0.10.0.
See `docs/operations/milestone-11.2.md`. Spoken-interruption latency and echo
acceptance remain Gate 10.

### Implement
- streaming STT,
- streaming TTS chunks,
- hard interruption,
- correction interruption,
- acknowledgement handling,
- TTS cancellation.

### Acceptance
- "stop" cancels audio promptly,
- "mhm" does not normally cancel,
- corrective interruption starts new request.

---

# Phase 12 — Advanced Voice / Multi-Speaker

## Milestone 12.0 — Speaker Recognition

### Implement
- speaker embedding provider,
- enrollment flow,
- confidence scoring,
- identity signal integration,
- replay-risk flagging.

### Acceptance
- speaker ID alone cannot authorize critical action,
- low confidence reduces privileges,
- owner/guest audio test suite is measurable.

---

## Milestone 12.1 — Diarization and Overlap Handling

### Implement
- diarization provider,
- per-speaker utterance streams,
- overlapping speech handling,
- background-vs-addressed classifier.

### Acceptance
- owner command remains separable from guest interference in benchmark scenarios,
- uncertainty produces safe clarification instead of destructive action.

---

## Milestone 12.2 — Spatial Audio [EXPERIMENTAL]

### Implement
Only on compatible hardware:
- source direction estimate,
- spatial metadata,
- UI/debug visualization.

### Acceptance
- feature is optional,
- absence of hardware does not affect normal voice.

---

# Phase 13 — Mobile and Device Mesh

## Milestone 13.0 — Device Identity and Pairing

### Implement
- device registry,
- keypair identity,
- QR/code pairing,
- trust level,
- revocation,
- protocol version.

### Acceptance
- unpaired device cannot call private APIs,
- revoked device cannot reconnect using old credentials.

---

## Milestone 13.1 — Mobile Client

### Implement
- mobile chat/voice shell,
- secure connection to core,
- active-session sync,
- selected local cache,
- capability advertisement.

### Acceptance
- phone can use desktop-hosted ADAM brain,
- private replication follows policy.

---

## Milestone 13.2 — Remote Capability Routing

### Implement
- remote tool request envelope,
- signed result,
- action idempotency,
- node health,
- remote filesystem-search demo.

### Acceptance
- phone request can safely execute allowed PC search,
- offline PC returns explicit unavailable state,
- retry does not duplicate critical action.

---

## Milestone 13.3 — Session Handoff

### Implement
- current-session handoff,
- primary interaction device,
- active task state sync.

### Acceptance
- desktop conversation can continue from phone with preserved working context.

---

# Phase 14 — Scheduling, Notifications, and Proactivity

## Milestone 14.0 — Scheduler

### Implement
- one-time tasks,
- recurring tasks,
- condition-watch interface,
- persistent scheduled-job store.

### Acceptance
- scheduled tasks survive restart,
- permissions are re-evaluated at execution time where necessary.

---

## Milestone 14.1 — Notification Router

### Implement
- active-device routing,
- priority,
- privacy-safe lock-screen content,
- desktop/mobile channels.

### Acceptance
- sensitive notification content is hidden when policy requires,
- offline device queues/redirects safely.

---

## Milestone 14.2 — Controlled Proactive Suggestions

### Implement
- explicit opt-in,
- trigger registry,
- quiet hours,
- anti-spam limits,
- explainable trigger.

### Acceptance
- proactive mode defaults off,
- every suggestion can explain why it appeared,
- no hidden passive surveillance is required.

---

# Phase 15 — Internet, Browser, and Integrations

## Milestone 15.0 — Web Retrieval Provider

### Implement
- web search interface,
- page fetch interface,
- source metadata,
- untrusted-content boundary,
- current/freshness metadata.

### Acceptance
- malicious page cannot trigger tool permissions,
- answers distinguish local memory from web evidence.

---

## Milestone 15.1 — MCP / External Tool Provider

### Implement
- provider registry,
- capability discovery,
- plugin trust policy,
- isolation boundaries.

### Acceptance
- plugin cannot escape declared capability scope,
- disconnecting provider removes capabilities cleanly.

---

## Milestone 15.2 — Browser Automation

### Implement
- explicit browser action tools,
- read/navigate/click/type,
- upload/download permission rules,
- dry-run/confirmation for sensitive actions.

### Acceptance
- page instructions never override user/system authorization,
- tool actions are auditable and cancellable.

---

# Phase 16 — Vision and Screen Understanding

## Milestone 16.0 — Image / Screenshot Perception

### Implement
- vision provider interface,
- image/screenshot events,
- privacy metadata,
- model routing.

### Acceptance
- ADAM accurately reports when vision is unavailable,
- image processing never grants action permission.

---

## Milestone 16.1 — Screen Understanding

### Implement
- opt-in capture,
- visible capture indicator,
- active-window metadata,
- screen-content reasoning.

### Acceptance
- capture is visibly indicated,
- private-app exclusions work.

---

# Phase 17 — Computer Use

## Milestone 17.0 — See / Plan / Act / Verify Pipeline

**Status:** `AUTOMATED_VERIFIED` on 2026-10-17 in paired release 0.17.0. Explicit owner actions support standard Win32 fields/buttons; source, frozen and installed fixture QA passed. Human Gate 16 remains `NOT_STARTED`; see [scope and evidence](docs/operations/waves-16-17-report.md).

### Implement
- UI action provider,
- permissioned clicks/typing,
- action preview,
- verification screenshots/state.

### Acceptance
- vision model cannot directly click,
- high-risk UI action requires policy/approval,
- action result is verified.

---

# Phase 18 — Installation, Updates, and Portability

## Milestone 18.0 — Guided Local Installer

**Status:** `AUTOMATED_VERIFIED` on 2026-10-17 in 0.17.0. Bundled current-user installer, hardware checks, owner setup and cancellable pinned model setup implemented. Clean VM installation, completed model download and human Gate 17 remain pending.

### Implement
- OS prerequisites,
- model/runtime checks,
- hardware profile,
- recommended initial brain,
- local data path,
- initial owner creation.

### Acceptance
- new user can install without hand-editing code,
- unsupported hardware gives clear reduced-mode choices.

---

## Milestone 18.1 — Update / Rollback

**Status:** `AUTOMATED_VERIFIED` on 2026-10-17 in 0.17.0. Checked managed packages, encrypted snapshots, cloned migration/health checks, atomic activation and rollback passed frozen-service and offline restart QA. Channels label explicit local releases; no external automatic update feed is configured. Human Gate 17 remains `NOT_STARTED`.

### Implement
- stable/beta/dev channels,
- pre-update snapshot,
- schema migration,
- post-update health/eval subset,
- rollback.

### Acceptance
- failed migration automatically returns to prior known-good version.

---

## Milestone 18.2 — Portable ADAM Restore

**Status:** `AUTOMATED_VERIFIED` on 2026-10-17 in 0.17.0. Encrypted portable restore preserved identity/history and booted a frozen service without original models. Model selection, reindexing and device repair guidance implemented. Another physical PC and Android re-pairing remain unverified; human Gate 17 remains `NOT_STARTED`.

### Implement
- portable package,
- hardware migration assistant,
- model re-selection,
- reindex background tasks,
- device re-pair workflow.

### Acceptance
- ADAM can move to a clean machine without original model,
- identity and personal history remain intact.

---

# Phase 19 — Advanced Personal Intelligence [LATER]

## Milestone 19.0 — Personal Knowledge Graph

Implementation status: `AUTOMATED_VERIFIED` in 0.20.0; human Gate 18 remains `NOT_STARTED`.

- people/projects/goals/events graph,
- relationship-aware retrieval,
- privacy inheritance.

## Milestone 19.1 — Personal Timeline

Implementation status: `AUTOMATED_VERIFIED` in 0.20.0, including source correction and historical/as-of views.

- historical events,
- project evolution,
- searchable time-based queries.

## Milestone 19.2 — Goal / Routine Intelligence

Implementation status: `AUTOMATED_VERIFIED` in 0.20.0. Goals are explicit; routines remain inferred suggestions and briefings are manually requested.

- user-authorized goal tracking,
- project progress,
- daily/weekly briefing input.

These must remain user-controlled and privacy-aware.

---

# Phase 20 — Optional Fine-Tuning [EXPERIMENTAL]

## Milestone 20.0 — Dataset Builder

Implementation status: `AUTOMATED_VERIFIED` in 0.20.0. Disabled by default; requires owner elevation and individual synthetic-example approval/export consent.

Collect only explicitly approved training examples derived from:
- preferred response behavior,
- tool-selection examples,
- formatting/style,
- structured-output tasks.

Do not train personal facts into weights.

## Milestone 20.1 — LoRA / QLoRA Experiment

Experiment status: `DEFERRED`. A bounded GPU recipe and report-comparison workflow are implemented, but no approved use case/dataset or trained adapter exists. The base model remains active; Gate 19 is deferred.

- train in Colab/Kaggle,
- compare against base model,
- run full migration/evaluation suite.

Promotion only if objectively useful.

---

# Phase 21 — Portfolio Release Hardening

## Milestone 21.0 — Demo Profile

Implementation status: `AUTOMATED_VERIFIED` in 0.20.0 with a separate fictional profile and scoped write/verify/undo sandbox; human Gate 20 remains `NOT_STARTED`.

- sanitized synthetic life data,
- sample projects,
- fake sensitive resources,
- safe tool sandbox.

## Milestone 21.1 — Benchmark Dashboard

Implementation status: `AUTOMATED_VERIFIED` in 0.20.0. The dashboard identifies scripted framework probes, measured scenario durations and unavailable VRAM/voice metrics; it does not present these as model-quality measurements.

Show:
- model,
- memory accuracy,
- RAG retrieval,
- tool accuracy,
- privacy/security pass rate,
- latency,
- VRAM usage,
- voice metrics when available.

## Milestone 21.2 — Public Documentation

Implementation status: `AUTOMATED_VERIFIED` in 0.20.0. Source delivery and GitHub preparation are local; nothing has been pushed or published. Human acceptance below remains pending.

Include:
- architecture diagram,
- threat model,
- model-independent design,
- evaluation methodology,
- limitations,
- privacy approach,
- demo instructions.

### Final acceptance
A recruiter can:
1. talk to ADAM,
2. inspect developer traces,
3. test RAG,
4. observe memory continuity,
5. test tools in safe demo mode,
6. see benchmark/evaluation evidence,
7. understand the architecture without accessing private owner data.

---

# Mandatory Release Gates Across All Milestones

Every milestone must satisfy:

- repository runs from a clean environment,
- tests pass,
- migrations work,
- no critical privacy regression,
- no critical security regression,
- no secret leakage,
- new public interface documented,
- new tool declares risk and scope,
- new persistent schema has migration,
- new feature has at least one failure-path test,
- feature flag exists for experimental behavior,
- developer trace includes new subsystem where relevant.

---

# Scope Discipline for Codex

When implementing a milestone, Codex must:

1. Read the Master Spec and current milestone.
2. Inspect existing repository contracts before modifying them.
3. Implement only the requested milestone and required supporting changes.
4. Preserve backward compatibility unless the milestone explicitly includes migration.
5. Add tests for all acceptance criteria.
6. Run tests and report failures honestly.
7. Avoid placeholders presented as completed functionality.
8. Avoid implementing future milestones "for convenience."
9. Document new architecture decisions.
10. Return a concise implementation report:
   - files changed,
   - features implemented,
   - tests run,
   - unresolved issues,
   - explicit non-implemented future features.

---

# Current Recommended Starting Point

Begin with:

**Milestone 0.1 — Repository and Contract Foundation**

Then proceed in order.

Do not jump directly to voice or avatar.

The purpose of this roadmap is to make future sophistication an extension of a stable runtime, not a sequence of rewrites.
