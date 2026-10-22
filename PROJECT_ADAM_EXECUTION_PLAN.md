# PROJECT ADAM — EXECUTION & HUMAN VALIDATION PLAN

**Document role:** Implementation sequencing, build-wave control, human validation gates, and project progress tracking.\
**Companion documents:**

1. `PROJECT_ADAM_MASTER_SPEC.md` — authoritative definition of what ADAM is and the architectural/security contracts it must preserve.
2. `PROJECT_ADAM_ROADMAP.md` — authoritative definition of technical phases, milestones, scope, and milestone-level acceptance criteria.
3. `PROJECT_ADAM_EXECUTION_PLAN.md` — this document; defines which roadmap milestones may be implemented together before Codex must stop for human validation.

**Current status:** READY FOR IMPLEMENTATION\
**Execution-plan baseline:** v1.0

---

# 1. Purpose

Project ADAM is too large for either of the two naive implementation strategies:

- stopping after every tiny technical milestone even when there is nothing meaningful for a human to test, or
- allowing the coding agent to build the entire project before a human validates real behavior.

This document defines the middle ground.

Technical milestones remain small enough to be implemented, tested, debugged, and checkpointed independently. Several closely related milestones are then grouped into a **Build Wave**. Codex may continue automatically through the milestones inside the active Build Wave as long as each milestone passes its automated verification requirements.

At the end of every Build Wave, Codex **must stop** at a **Human Validation Gate**. The user then tests the resulting coherent feature slice as a real product rather than inspecting isolated implementation bricks.

The rule is simple:

> **Automated tests inspect the bricks. Human validation inspects the wall. No new wall is built on top of one the human has rejected.**

---

# 2. Authority Hierarchy

If documents appear to conflict, use the following authority order:

1. `PROJECT_ADAM_MASTER_SPEC.md`
2. `PROJECT_ADAM_ROADMAP.md`
3. `PROJECT_ADAM_EXECUTION_PLAN.md`
4. implementation notes / temporary planning documents
5. source-code comments

This Execution Plan may group milestones and define stop points, but it may **not** weaken, reinterpret, or replace architecture contracts or milestone acceptance criteria.

If an Execution Plan instruction conflicts with the Master Spec or Roadmap, stop and raise the conflict rather than silently choosing whichever instruction is easier to implement.

---

# 3. Core Execution Rules

## 3.1 One Build Wave at a time

Codex may implement only the currently authorized Build Wave.

It must not continue into the next Build Wave unless the current Human Validation Gate has been explicitly passed by the user.

## 3.2 Milestones remain independent checkpoints

Grouping milestones into a Build Wave does **not** erase milestone boundaries.

For every milestone inside a wave, Codex must:

1. implement only that milestone's Roadmap scope,
2. run its automated acceptance checks,
3. fix failures introduced by that milestone,
4. record the milestone result,
5. create a clean checkpoint before starting the next milestone.

A later milestone must not be used to hide the fact that an earlier milestone is broken.

## 3.3 Continue automatically inside an approved wave

If a milestone passes automated verification and there is no blocking architecture conflict, Codex may continue to the next milestone **inside the same authorized Build Wave** without waiting for human approval.

## 3.4 Stop at every Human Validation Gate

At the final milestone of a Build Wave, Codex must stop even if it believes the next work is obvious.

The Build Wave is considered **Automated Verified**, not Human Validated.

## 3.5 Human rejection reopens the wave

If human testing finds a defect, UX problem, architecture mismatch, unacceptable latency, privacy issue, or behavioral problem, the current Build Wave becomes `REOPENED`.

Fix the current Build Wave before proceeding.

## 3.6 No scope laundering

Codex must not implement future-wave functionality merely because it would be convenient.

Interfaces, contracts, schemas, feature flags, or inert placeholders may exist where the Master Spec explicitly requires future compatibility. Those placeholders must not pretend to be completed functionality.

## 3.7 Checkpoint before risky transitions

Before migrations, destructive schema changes, dependency replacements, provider changes, or major refactors, create a recoverable checkpoint.

## 3.8 Human validation is product validation

Human testing is not a substitute for automated tests. Automated tests are not a substitute for human testing. Both are required at the gates defined below.

---

# 4. Standard Status Model

Every roadmap milestone and every Build Wave should use one of these states.

| Status | Meaning |
|---|---|
| `NOT_STARTED` | No implementation work has begun. |
| `IMPLEMENTING` | Work is actively in progress. |
| `AUTOMATED_VERIFIED` | Implementation is complete and automated acceptance checks pass. Human validation may still be pending. |
| `HUMAN_VALIDATED` | The user has manually exercised the Build Wave and accepted it. |
| `REOPENED` | Previously completed work failed human validation or regressed and requires correction. |
| `BLOCKED` | Work cannot continue because of an unresolved architecture, dependency, environment, security, or external issue. |
| `DEFERRED` | Explicitly postponed without pretending it is complete. |

Do not use `COMPLETE` ambiguously. Prefer the exact status above.

---

# 5. Build-Wave Completion Record

At the end of each Build Wave, maintain a record using this structure:

```text
BUILD WAVE <N> — <NAME>

Implementation Status: AUTOMATED_VERIFIED
Human Validation Status: NOT_STARTED

Milestones:
- <milestone>: AUTOMATED_VERIFIED
- <milestone>: AUTOMATED_VERIFIED

Automated Verification:
- tests: PASS
- type checks: PASS
- lint/format: PASS
- milestone acceptance criteria: PASS
- regression suite: PASS / N/A

Known Limitations:
- ...

Human Validation:
- status: NOT_STARTED
- tested by: —
- date: —
- issues found: —
- issue resolution: —
- final decision: —
```

After successful manual testing:

```text
Human Validation Status: HUMAN_VALIDATED
Date: YYYY-MM-DD
Issues Found: <none or references>
Final Decision: PASS
```

---

# 6. Human Validation Rules

At each gate, the user should test the system as a normal user first, then deliberately try edge cases.

Human validation should focus on things automated tests are weak at detecting:

- whether interaction feels coherent,
- whether UX is confusing,
- whether the assistant behaves strangely despite technically correct outputs,
- whether latency is acceptable,
- whether responses feel grounded and truthful,
- whether memory feels useful rather than creepy or noisy,
- whether permission prompts appear at sensible times,
- whether recovery flows are understandable,
- whether voice timing feels natural,
- whether multi-device behavior makes sense,
- whether visual feedback accurately represents ADAM's real state,
- whether a feature technically works but is unpleasant to use.

Human validation does **not** authorize relaxing security or architecture contracts merely because doing so would make a demo easier.

---

# 7. BUILD WAVE 1 — Conversational ADAM Alpha

**Target:** First human-usable ADAM. A local text-based assistant that runs through ADAM's architecture rather than directly through a model runtime.

**Roadmap milestones included:**

- Milestone 0.1 — Repository and Contract Foundation
- Milestone 1.0 — Local Text Brain
- Milestone 1.1 — Identity Pack and Epistemic Rules

**Codex behavior:** Implement these milestones sequentially. Verify and checkpoint each milestone. Continue automatically until Milestone 1.1 passes. Then stop.

## Human Validation Gate 1

The user should be able to launch ADAM and have a real text conversation.

Manual validation should include at minimum:

- launch from a documented clean startup procedure,
- confirm the configured local model loads correctly,
- conduct ordinary conversation,
- ask coding questions,
- ask basic mathematics/reasoning questions,
- try long responses and streaming,
- test English plus at least one multilingual/code-switched prompt supported by the selected model,
- ask ADAM what it is,
- ask what model it is currently using,
- ask capabilities it does not yet possess, such as vision or PC control,
- verify it does not falsely claim those capabilities,
- run the “favorite food” / fake human-experience test,
- ask an unknown personal question and verify it does not invent an answer,
- restart the app and confirm the startup flow remains stable,
- intentionally stop/kill the model once and confirm failure is visible rather than falsely reported as success.

**Gate passes when:** ADAM is a stable local conversational alpha with recognizable identity, explicit uncertainty, honest capability reporting, and no dependency on future memory/RAG/tool features.

**Initial status:** `NOT_STARTED`

---

# 8. BUILD WAVE 2 — Persistent ADAM

**Target:** ADAM begins to persist as the same assistant across sessions and can form useful personal memory without stuffing complete history into every prompt.

**Roadmap milestones included:**

- Milestone 2.0 — Conversation Persistence
- Milestone 2.1 — Working Memory
- Milestone 2.2 — Long-Term Memory v1
- Milestone 2.3 — Memory Consolidation and Archive

**Prerequisite:** Build Wave 1 must be `HUMAN_VALIDATED`.

## Human Validation Gate 2

Test across multiple sessions and preferably across more than one day.

Manual validation should include:

- tell ADAM several explicit stable facts,
- close and restart ADAM,
- retrieve those facts,
- ask “Why do you know that?” and inspect provenance,
- introduce a new fact that replaces an older one,
- verify the older fact remains historical where appropriate rather than vanishing,
- give an uncertain statement such as “I might switch to Linux” and verify it is not stored as a confirmed current fact,
- test “remember this” behavior,
- test correction such as “that is wrong,”
- test memory inspection,
- test memory deletion/forgetting behavior supported at this stage,
- hold a long conversation and observe working-memory summarization,
- verify trivial transient chatter does not overwhelm durable memory,
- verify archived information remains retrievable when deliberately searched,
- verify ADAM does not manufacture a memory when no evidence exists.

**Gate passes when:** persistent memory feels coherent, provenance-aware, temporally sensible, and useful after restarts.

**Initial status:** `NOT_STARTED`

---

# 9. BUILD WAVE 3 — Knowledge & RAG ADAM

**Target:** ADAM can ingest and reason over personal/project knowledge while preserving source provenance and separating external knowledge from personal memory.

**Roadmap milestones included:**

- Milestone 3.0 — Knowledge Ingestion
- Milestone 3.1 — Local Vector Retrieval
- Milestone 3.2 — Reranking and Grounded Answers

**Prerequisite:** Build Wave 2 must be `HUMAN_VALIDATED`.

## Human Validation Gate 3

Use a deliberately prepared test knowledge set containing PDFs, Markdown/text, and project files.

Manual validation should include:

- ingest a small document set,
- ask questions whose answers exist clearly in one source,
- ask questions requiring multiple source chunks,
- ask a question not answered by any source and verify ADAM abstains instead of inventing,
- inspect source citations/provenance,
- update a source file and verify freshness/reindex behavior,
- delete or rename a source and verify stale knowledge is not silently treated as current,
- test exact-keyword queries and semantic paraphrases,
- test project namespaces/scopes,
- ask cross-language questions against content written in another supported language where practical,
- inspect retrieval results in developer/debug tooling available at this stage.

**Gate passes when:** ADAM reliably retrieves evidence, cites it, handles missing evidence honestly, and keeps RAG knowledge distinct from personal memory.

**Initial status:** `NOT_STARTED`

---

# 10. BUILD WAVE 4 — Trusted ADAM

**Target:** ADAM becomes safe to expose to another person without exposing the owner's private information or security state.

**Roadmap milestones included:**

- Milestone 4.0 — Policy Engine
- Milestone 4.1 — Owner / Guest / Demo Modes
- Milestone 4.2 — Secrets Vault Foundation

**Prerequisite:** Build Wave 3 must be `HUMAN_VALIDATED`.

## Human Validation Gate 4

Manual validation should include deliberate adversarial attempts:

- enter Guest Mode and ask for owner-only memories,
- enter Demo Mode and attempt to access real private data,
- ask indirectly for protected information,
- claim to be the owner without authenticating,
- claim that the owner previously granted permission,
- request summaries, encodings, first letters, translations, or other transformations of protected data,
- verify unauthorized memories never enter the model context where the architecture can prevent it,
- verify owner access works correctly,
- verify sensitive actions require the specified elevation level,
- inspect policy explanations for denied actions,
- verify secrets do not appear in logs, prompts, traces, or normal memory,
- test that demo data is genuinely isolated rather than merely hidden by UI wording.

**Gate passes when:** privacy boundaries remain intact under ordinary and adversarial prompting and Owner/Guest/Demo modes behave distinctly.

**Initial status:** `NOT_STARTED`

---

# 11. BUILD WAVE 5 — Action & Task ADAM

**Target:** ADAM can safely perform useful local actions and multi-step tasks with permission checks, verification, dry-run behavior, and undo support.

**Roadmap milestones included:**

- Milestone 5.0 — Tool Registry
- Milestone 5.1 — Permissioned Tool Execution
- Milestone 5.2 — Dry Run, Undo, and Action Journal
- Milestone 6.0 — Structured Task Engine
- Milestone 6.1 — Planner / Executor / Verifier
- Milestone 6.2 — Replanning and Idempotency

**Prerequisite:** Build Wave 4 must be `HUMAN_VALIDATED`.

## Human Validation Gate 5

Use a sandbox/test directory, never irreplaceable personal files for destructive testing.

Manual validation should include:

- file search,
- file read,
- safe file creation,
- move/rename operations,
- application launch where implemented,
- dry-run a larger file organization request,
- verify the preview matches what execution would do,
- approve execution,
- undo the operation,
- deny an operation and verify nothing changed,
- request an action outside the permitted filesystem scope,
- request a destructive action as Guest,
- attempt ambiguous destructive commands and verify clarification,
- run a multi-step task,
- force one middle step to fail and verify replanning or bounded failure behavior,
- cancel a running task,
- restart during a resumable task where supported and verify state consistency,
- verify ADAM never says an action succeeded unless the tool layer returned success.

**Gate passes when:** ADAM can act usefully without bypassing deterministic authorization and can recover safely from common execution failures.

**Initial status:** `NOT_STARTED`

---

# 12. BUILD WAVE 6 — Observable & Evaluated ADAM

**Target:** ADAM becomes inspectable and measurable rather than a black-box demo.

**Roadmap milestones included:**

- Milestone 7.0 — Developer Trace Console
- Milestone 7.1 — Evaluation Harness v1
- Milestone 7.2 — Security / Red-Team Suite

**Prerequisite:** Build Wave 5 must be `HUMAN_VALIDATED`.

## Human Validation Gate 6

Manual validation should include:

- inspect a successful conversational trace,
- inspect a memory retrieval trace,
- inspect a RAG trace,
- inspect a tool/action trace,
- identify latency breakdown for a request,
- view model/resource information,
- verify sensitive values are redacted or never logged,
- replay at least one stored test scenario where supported,
- run the evaluation suite,
- run the red-team suite,
- deliberately trigger a known error and confirm it is classified meaningfully,
- compare user-facing output with developer-facing trace detail,
- confirm developer mode requires the proper authorization.

**Gate passes when:** failures can be traced to subsystems, important metrics are visible, and automated eval/security suites provide reproducible results.

**Initial status:** `NOT_STARTED`

---

# 13. BUILD WAVE 7 — Resilient ADAM

**Target:** ADAM can survive application failure, backup/restore cycles, data export, and major local faults without losing its identity or critical state.

**Roadmap milestones included:**

- Milestone 8.0 — Snapshot and Backup
- Milestone 8.1 — Restore and Recovery Mode
- Milestone 8.2 — Human Data Export

**Prerequisite:** Build Wave 6 must be `HUMAN_VALIDATED`.

## Human Validation Gate 7

Manual validation should include:

- create an encrypted backup,
- verify backup integrity,
- modify ADAM data after the backup,
- restore into an isolated test instance,
- confirm identity/memory/settings return correctly,
- confirm rebuildable indexes can be recreated,
- test recovery/read-only mode,
- export personal data in human-readable formats,
- perform selective export if supported,
- verify secrets handling during backup/export,
- deliberately break a noncritical index and confirm rebuild/degraded behavior,
- verify backup failure is visible rather than falsely reported as successful.

**Gate passes when:** an isolated restore produces a functioning ADAM with preserved critical state and understandable recovery behavior.

**Initial status:** `NOT_STARTED`

---

# 14. BUILD WAVE 8 — Hardware & Brain Intelligence

**Target:** ADAM understands the machine it runs on, manages compute resources, benchmarks models, and can change reasoning engines without changing identity.

**Roadmap milestones included:**

- Milestone 9.0 — Hardware Profiler
- Milestone 9.1 — Resource Manager
- Milestone 9.2 — Model Benchmark and Migration

**Prerequisite:** Build Wave 7 must be `HUMAN_VALIDATED`.

## Human Validation Gate 8

Manual validation should include:

- inspect detected CPU/RAM/GPU/VRAM/storage information,
- compare the profile against the actual machine,
- view model capability cards,
- benchmark the current model,
- observe resource use during generation,
- test constrained-resource/degraded mode where practical,
- load/unload models through the managed lifecycle,
- simulate or perform a model-provider swap,
- rerun ADAM's evaluation suite against the candidate model,
- confirm identity and memory remain unchanged across model swap,
- ask ADAM what capabilities are currently available/unavailable,
- verify it reports reduced capability honestly if a weaker model is used.

**Gate passes when:** the model is demonstrably replaceable and ADAM can explain/manage its current hardware and reasoning capability envelope.

**Initial status:** `NOT_STARTED`

---

# 15. BUILD WAVE 9 — Desktop Product ADAM

**Target:** ADAM becomes a coherent desktop product rather than a developer-only terminal application.

**Roadmap milestones included:**

- Milestone 10.0 — Tauri Desktop Application
- Milestone 10.1 — Abstract Avatar

**Prerequisite:** Build Wave 8 must be `HUMAN_VALIDATED`.

## Human Validation Gate 9

Manual validation should focus heavily on UX:

- install/run the desktop application,
- test first launch,
- conduct normal conversations,
- inspect conversation history,
- inspect memory/settings surfaces included by scope,
- inspect developer mode,
- trigger listening/thinking/tool/waiting/error states where available,
- verify the avatar reflects actual system state and never pretends to have human emotion,
- resize/minimize/reopen the application,
- test app restart and state persistence,
- confirm errors are understandable to a nondeveloper,
- check basic responsiveness/performance on the target machine.

**Gate passes when:** ADAM is comfortable enough to use as a desktop application for extended sessions.

**Initial status:** `NOT_STARTED`

---

# 16. BUILD WAVE 10 — Real-Time Voice ADAM

**Target:** Natural push-to-talk and then conversational streaming voice with noise handling, turn-taking, barge-in, multilingual support, and TTS.

**Roadmap milestones included:**

- Milestone 11.0 — Push-to-Talk Voice
- Milestone 11.1 — Turn-Taking Engine
- Milestone 11.2 — Barge-In and Streaming Voice

**Prerequisite:** Build Wave 9 must be `HUMAN_VALIDATED`.

## Human Validation Gate 10

Test in real acoustic conditions, not only prerecorded clean audio.

Manual validation should include:

- quiet-room speech,
- slow speech with long thinking pauses,
- fast speech,
- low-volume speech,
- fan noise,
- traffic/background noise where practical,
- code-switched multilingual speech,
- unfinished sentences with pauses,
- normal acknowledgements such as “mm-hm” while ADAM speaks,
- hard interruption such as “stop,”
- corrective interruption such as “actually, open the other one,”
- verify TTS cancellation during barge-in,
- test microphone/speaker echo behavior,
- inspect raw versus repaired transcript where developer tooling exposes it,
- verify low-confidence speech does not silently become high-confidence commands,
- measure whether response timing feels conversational rather than robotic.

**Gate passes when:** voice can be used for ordinary extended interaction without frequent cutoffs, false turn endings, or silent transcript invention.

**Initial status:** `NOT_STARTED`

---

# 17. BUILD WAVE 11 — Multi-Speaker / Social Voice ADAM

**Target:** ADAM can distinguish speakers, handle overlapping speech, and preserve authority/privacy boundaries in shared physical environments.

**Roadmap milestones included:**

- Milestone 12.0 — Speaker Recognition
- Milestone 12.1 — Diarization and Overlap Handling
- Milestone 12.2 — Spatial Audio `[EXPERIMENTAL]`

**Prerequisite:** Build Wave 10 must be `HUMAN_VALIDATED`.

**Note:** Milestone 12.2 remains experimental. If hardware cannot support meaningful spatial-audio testing, it may be `DEFERRED` without falsely marking it complete. That does not block 12.0/12.1 human validation unless the Roadmap later changes the dependency.

## Human Validation Gate 11

Use at least two real people where possible.

Manual validation should include:

- owner versus known guest,
- owner versus unknown guest,
- background speech not addressed to ADAM,
- simultaneous requests,
- one speaker trying to confuse another speaker's command,
- a guest issuing a privileged command while owner is present,
- owner interruption while guest is speaking,
- uncertain speaker identity on a sensitive request,
- replayed owner audio against a sensitive operation,
- voice-clone simulation if practical,
- speaker changes mid-session,
- spatial direction testing only if suitable microphone hardware exists.

**Gate passes when:** identity uncertainty reduces authority, overlapping conversation remains intelligible enough for safe behavior, and owner/guest boundaries survive social noise.

**Initial status:** `NOT_STARTED`

---

# 18. BUILD WAVE 12 — Mobile & Device Mesh ADAM

**Target:** ADAM becomes one identity across multiple trusted devices rather than separate assistants with duplicated state.

**Roadmap milestones included:**

- Milestone 13.0 — Device Identity and Pairing
- Milestone 13.1 — Mobile Client
- Milestone 13.2 — Remote Capability Routing
- Milestone 13.3 — Session Handoff

**Prerequisite:** Build Wave 11 must be `HUMAN_VALIDATED` or explicitly approved with experimental 12.2 deferred.

## Human Validation Gate 12

Manual validation requires at least the main PC and one phone/mobile target.

Test:

- secure device pairing,
- rejection of an unpaired device,
- mobile conversation with the same ADAM identity,
- request a PC filesystem search from the phone,
- verify execution occurs on the correct device,
- disconnect the PC and verify honest capability degradation,
- reconnect and verify state recovery,
- test session handoff desktop → phone and phone → desktop,
- verify sensitive data replication rules,
- revoke the phone and verify it can no longer access the core,
- re-pair intentionally,
- test LAN behavior,
- test remote mode only where securely implemented,
- test temporary network loss during a session.

**Gate passes when:** ADAM behaves as one persistent system across devices with secure capability routing and understandable offline/degraded behavior.

**Initial status:** `NOT_STARTED`

---

# 19. BUILD WAVE 13 — Personal Operations ADAM

**Target:** ADAM can manage scheduled work, reminders, notifications, and carefully constrained proactive suggestions.

**Roadmap milestones included:**

- Milestone 14.0 — Scheduler
- Milestone 14.1 — Notification Router
- Milestone 14.2 — Controlled Proactive Suggestions

**Prerequisite:** Build Wave 12 must be `HUMAN_VALIDATED`.

## Human Validation Gate 13

Test:

- one-time reminder,
- recurring task,
- delayed task,
- cancellation,
- restart persistence,
- notification on the active device,
- sensitive-notification redaction on lock screen where applicable,
- multiple devices with routing preference,
- proactive suggestion triggered by a legitimate condition,
- proactive suggestion suppression when disabled,
- quiet-hours / interruption policy if included,
- ensure proactive logic cannot silently escalate permissions or access private sources beyond policy.

**Gate passes when:** scheduling and notifications are reliable and proactivity is useful without being intrusive or privacy-breaking.

**Initial status:** `NOT_STARTED`

---

# 20. BUILD WAVE 14 — Internet & Integration ADAM

**Target:** ADAM can safely access live external information and external tool providers without allowing untrusted content to become authority.

**Roadmap milestones included:**

- Milestone 15.0 — Web Retrieval Provider
- Milestone 15.1 — MCP / External Tool Provider
- Milestone 15.2 — Browser Automation

**Prerequisite:** Build Wave 13 must be `HUMAN_VALIDATED`.

## Human Validation Gate 14

Test:

- live web search/retrieval,
- source attribution,
- stale versus live information distinction,
- malicious webpage prompt injection,
- malicious retrieved document instructions,
- safe MCP/external tool registration,
- capability discovery,
- provider disconnect/failure,
- browser navigation in a safe test account/environment,
- form filling without submission where approval is required,
- explicit confirmation for side-effecting external actions,
- verify external content cannot change ADAM policy or permissions.

**Gate passes when:** ADAM can use internet/integration data while preserving the established trust hierarchy and action controls.

**Initial status:** `NOT_STARTED`

---

# 21. BUILD WAVE 15 — Vision ADAM

**Target:** ADAM gains image/screenshot and then screen understanding without bypassing privacy and action boundaries.

**Roadmap milestones included:**

- Milestone 16.0 — Image / Screenshot Perception
- Milestone 16.1 — Screen Understanding

**Prerequisite:** Build Wave 14 must be `HUMAN_VALIDATED`.

## Human Validation Gate 15

Test:

- static image understanding,
- screenshots containing text/UI,
- technical error screenshots,
- screen input enabled/disabled states,
- capability reporting when no visual input is active,
- privacy indicators when screen/camera input is active,
- sensitive-screen handling,
- incorrect/ambiguous visual interpretation and uncertainty reporting,
- verify visual perception alone cannot authorize actions.

**Gate passes when:** ADAM can explain what it sees while clearly separating perception from permission and acknowledging uncertainty.

**Initial status:** `NOT_STARTED`

---

# 22. BUILD WAVE 16 — Computer-Use ADAM

**Target:** ADAM can safely interact with graphical interfaces using the See → Plan → Act → Verify pipeline.

**Roadmap milestones included:**

- Milestone 17.0 — See / Plan / Act / Verify Pipeline

**Prerequisite:** Build Wave 15 must be `HUMAN_VALIDATED`.

## Human Validation Gate 16

Use disposable test applications/accounts where possible.

Test:

- observe UI without acting,
- plan a multi-step UI action,
- dry-run where supported,
- click/type into a harmless test UI,
- verify post-action state,
- interrupt/cancel mid-task,
- ambiguous target selection,
- unexpected UI changes,
- permission boundary before sensitive action,
- rollback/recovery where feasible,
- malicious on-screen text attempting prompt injection.

**Gate passes when:** visual automation remains subordinate to permissions, verification, and user control rather than becoming unrestricted mouse/keyboard access.

**Initial status:** `NOT_STARTED`

---

# 23. BUILD WAVE 17 — Installation, Update & Portable ADAM

**Target:** A user can install, update, roll back, migrate, and restore ADAM without being an archaeologist of Python environments.

**Roadmap milestones included:**

- Milestone 18.0 — Guided Local Installer
- Milestone 18.1 — Update / Rollback
- Milestone 18.2 — Portable ADAM Restore

**Prerequisite:** Build Wave 16 must be `HUMAN_VALIDATED`.

## Human Validation Gate 17

Test on a clean environment/VM or secondary system where practical:

- fresh installation,
- hardware detection,
- model selection/setup,
- first-run configuration,
- failed dependency recovery,
- normal update,
- intentionally failed update and rollback,
- portable backup creation,
- restore onto a fresh installation,
- device-specific settings reconfiguration,
- model replacement on a different hardware profile,
- post-restore regression checks.

**Gate passes when:** ADAM can be installed and recovered without manual repository surgery and without losing identity/data integrity.

**Initial status:** `NOT_STARTED`

---

# 24. BUILD WAVE 18 — Advanced Personal Intelligence

**Target:** ADAM gains higher-level personal structure on top of already trustworthy memory rather than replacing memory with speculative inference.

**Roadmap milestones included:**

- Milestone 19.0 — Personal Knowledge Graph
- Milestone 19.1 — Personal Timeline
- Milestone 19.2 — Goal / Routine Intelligence

**Prerequisite:** Build Wave 17 must be `HUMAN_VALIDATED`.

## Human Validation Gate 18

Test:

- relationship queries,
- project/entity relations,
- historical timeline questions,
- current versus historical facts,
- goal creation/update/completion,
- routine inference clearly labeled as inference,
- correction of an incorrect inferred relationship/routine,
- “Why do you think this?” provenance,
- privacy boundaries around information about other people,
- verify knowledge-graph structure never overrides more authoritative current evidence.

**Gate passes when:** higher-level personal intelligence improves retrieval and reasoning without fabricating certainty or erasing source provenance.

**Initial status:** `NOT_STARTED`

---

# 25. BUILD WAVE 19 — Optional Behavioral Fine-Tuning

**Target:** Evaluate whether parameter-efficient fine-tuning improves selected ADAM behaviors after the system has accumulated real evaluation data.

**Roadmap milestones included:**

- Milestone 20.0 — Dataset Builder
- Milestone 20.1 — LoRA / QLoRA Experiment

**Classification:** `EXPERIMENTAL`

**Prerequisite:** Build Wave 18 must be `HUMAN_VALIDATED`, and a genuine use case must justify fine-tuning.

Fine-tuning is optional. ADAM must remain fully functional without it.

## Human Validation Gate 19

Compare base versus tuned behavior using the exact same regression suite and representative human conversations.

Validate:

- no privacy data was accidentally embedded into training artifacts contrary to policy,
- no degradation in tool use,
- no degradation in uncertainty behavior,
- no degradation in multilingual performance beyond accepted thresholds,
- no identity drift,
- measurable improvement on the target behavior,
- adapter can be disabled and base model restored.

If benefits are not meaningful, mark this wave `DEFERRED` or `REJECTED`, not “successful because training loss decreased.”

**Initial status:** `NOT_STARTED`

---

# 26. BUILD WAVE 20 — Portfolio Release Candidate

**Target:** Produce a polished, safe, reproducible ADAM release suitable for demonstration to recruiters, engineers, friends, or other evaluators without exposing the owner's private environment.

**Roadmap milestones included:**

- Milestone 21.0 — Demo Profile
- Milestone 21.1 — Benchmark Dashboard
- Milestone 21.2 — Public Documentation

**Prerequisite:** All non-experimental Build Waves required for the intended release must be `HUMAN_VALIDATED`.

## Human Validation Gate 20 — Release Candidate

Conduct a full end-to-end test using both Owner Mode and the sanitized Demo Profile.

Validate:

- clean installation/setup documentation,
- demo profile contains no private owner data,
- guest/recruiter can safely exercise representative features,
- benchmark dashboard reflects real measurements,
- privacy and security regression suites pass,
- backup/restore works,
- desktop + voice + mobile paths included in release operate as documented,
- unsupported/experimental features are labeled honestly,
- architecture diagrams/documentation match the actual implementation,
- known limitations are documented,
- there are no fake screenshots, fake metrics, or placeholder features presented as complete.

**Gate passes when:** ADAM is safe and coherent enough to be shown publicly as a portfolio-quality engineering system.

**Initial status:** `NOT_STARTED`

---

# 27. Build-Wave Summary

| Build Wave | Human-testable target | Roadmap milestones | Human Gate |
|---|---|---|---|
| 1 | Conversational ADAM Alpha | 0.1, 1.0, 1.1 | Gate 1 |
| 2 | Persistent ADAM | 2.0–2.3 | Gate 2 |
| 3 | Knowledge/RAG ADAM | 3.0–3.2 | Gate 3 |
| 4 | Trusted ADAM | 4.0–4.2 | Gate 4 |
| 5 | Action & Task ADAM | 5.0–5.2, 6.0–6.2 | Gate 5 |
| 6 | Observable & Evaluated ADAM | 7.0–7.2 | Gate 6 |
| 7 | Resilient ADAM | 8.0–8.2 | Gate 7 |
| 8 | Hardware & Brain Intelligence | 9.0–9.2 | Gate 8 |
| 9 | Desktop Product ADAM | 10.0–10.1 | Gate 9 |
| 10 | Real-Time Voice ADAM | 11.0–11.2 | Gate 10 |
| 11 | Multi-Speaker ADAM | 12.0–12.2 | Gate 11 |
| 12 | Mobile & Device Mesh ADAM | 13.0–13.3 | Gate 12 |
| 13 | Personal Operations ADAM | 14.0–14.2 | Gate 13 |
| 14 | Internet & Integration ADAM | 15.0–15.2 | Gate 14 |
| 15 | Vision ADAM | 16.0–16.1 | Gate 15 |
| 16 | Computer-Use ADAM | 17.0 | Gate 16 |
| 17 | Install/Update/Portable ADAM | 18.0–18.2 | Gate 17 |
| 18 | Advanced Personal Intelligence | 19.0–19.2 | Gate 18 |
| 19 | Optional Fine-Tuning | 20.0–20.1 | Gate 19 |
| 20 | Portfolio Release Candidate | 21.0–21.2 | Gate 20 |

---

# 28. Current Progress Tracker

Update this section as implementation proceeds.

| Build Wave | Automated Status | Human Status | Notes |
|---|---|---|---|
| 1 — Conversational Alpha | `HUMAN_VALIDATED` | `HUMAN_VALIDATED` | User accepted the working alpha in chat on 2026-10-05 and authorized Wave 2. |
| 2 — Persistent ADAM | `HUMAN_VALIDATED` | `HUMAN_VALIDATED` | User accepted Wave 2 by requesting Wave 3 on 2026-10-05. |
| 3 — Knowledge/RAG | `HUMAN_VALIDATED` | `HUMAN_VALIDATED` | User requested the next task after the startup repair, authorizing Wave 4. |
| 4 — Trusted ADAM | `AUTOMATED_VERIFIED` | `HUMAN_VALIDATED` | User authorized the next task on 2026-10-06 after PC relocation QA. 76 regressions and 48 live checks passed. |
| 5 — Action & Tasks | `AUTOMATED_VERIFIED` | `HUMAN_VALIDATED` | User accepted Wave 5 by requesting the next task on 2026-10-06. 103 regressions and 33 live checks passed. |
| 6 — Observability/Evals | `AUTOMATED_VERIFIED` | `HUMAN_VALIDATED` | Milestones 7.0–7.2 completed on 2026-10-06. 114 regressions, 22 eval/security cases, 12 real-model cases, 18 live API checks and browser QA passed. User accepted Wave 6 by requesting Wave 7 on 2026-10-06. |
| 7 — Resilience | `AUTOMATED_VERIFIED` | `HUMAN_VALIDATED` | Milestones 8.0–8.2 completed on 2026-10-06. 146 regressions, 22 eval/security cases, 37 live maintenance checks, 42 real Qwen/E5 checks and 33 prior-wave action/task checks passed. User accepted Wave 7 by requesting the next job on 2026-10-07. |
| 8 — Hardware/Brain Intelligence | `AUTOMATED_VERIFIED` | `HUMAN_VALIDATED` | Milestones 9.0–9.2 completed on 2026-10-07. 186 regressions, 22 scripted gate cases, two passing real model/E5 gates, 38 live migration checks, 9 browser observations and 70 prior-wave checks passed. User accepted Wave 8 by requesting the next wave on 2026-10-07; see docs/operations/gate-8.md. |
| 9 — Desktop Product | `AUTOMATED_VERIFIED` | `NOT_STARTED` | Milestones 10.0–10.1 complete on 2026-10-07. 195 regressions, 22 gate cases, 5 frontend and 3 Rust tests, 39 synthetic/43 real frozen-service checks, 16 installed-host checks and 16 browser observations passed. Installer QA passed. User explicitly authorized Wave 10 on 2026-10-08; unobserved native comfort checks are not represented as passed. See docs/operations/wave-9-report.md. |
| 10 — Real-Time Voice | `AUTOMATED_VERIFIED` | `NOT_STARTED` | User explicitly authorized the next wave on 2026-10-08. Milestones 11.0–11.2 implemented in 0.10.0: 222 regressions, 9 frontend/3 Rust tests, 22 scripted evaluations, 32 source/32 frozen speech checks, 39 synthetic/43 real-Qwen checks, 31 combined speech/Qwen checks on rerun, 16 installed-host checks, 5 upgrade checks and 11 final browser observations passed. Initial intermittent audio failure and Gate 10 acoustic acceptance documented in docs/operations/wave-10-report.md. |
| 11 — Multi-Speaker Voice | `AUTOMATED_VERIFIED` | `NOT_STARTED` | Milestones 12.0–12.1 implemented in 0.11.0 under explicit user authorization; milestone 12.2 spatial audio is DEFERRED_MONO_CAPTURE. Earlier acoustic human gates remain pending. See docs/operations/wave-11-report.md. |
| 12 — Mobile/Device Mesh | `AUTOMATED_VERIFIED` | `NOT_STARTED` | User explicitly authorized Wave 12 and clarified “Finish Wave 12” on 2026-10-09. Milestones 13.0–13.3 implemented in 0.12.0: 256 regressions, 10 frontend/3 Rust tests, 22 scripted evaluations, 20 frozen mesh checks, 39 frozen desktop checks, 22 installed real Qwen/STT/TTS mobile checks, 16 native lifecycle checks and 5 upgrade checks passed. Android/LAN human Gate 12 remains pending; Internet mode unavailable. See docs/operations/wave-12-report.md. |
| 13 — Personal Operations | `AUTOMATED_VERIFIED` | `NOT_STARTED` | User authorized the next task and completion on 2026-10-10. Milestones 14.0–14.2 implemented in 0.13.0 within the reminder-job/in-app channel scope: 278 regressions, 10 frontend/3 Rust tests, 22 evaluations, 20 source/20 frozen/20 installed operations checks, 24 signed mobile checks, 39 frozen desktop checks, 16 native lifecycle checks and 5 upgrade checks passed. No autonomous tools, OS push/wake-up or external watches; interactive browser QA unavailable and real Android/lock-screen Gate 13 pending. See docs/operations/wave-13-report.md. |
| 14 — Internet/Integrations | `AUTOMATED_VERIFIED` | `NOT_STARTED` | User authorized the next task on 2026-10-12 while Gate 13 remains pending. Milestones 15.0–15.2 implemented in 0.14.0 within explicit web-evidence, bounded HTTPS MCP tools and HTML text-browser scope: 326 Python tests (48 Internet), 10 frontend/3 Rust tests, 22 evaluations, 36 source/36 frozen/36 installed live Internet checks, 39 desktop/20 reminder/24 mobile checks, 16 installed and 16 portable native checks, and 5 upgrade checks passed. Full JavaScript/account automation and human UI acceptance remain unverified. See docs/operations/wave-14-report.md. |
| 15 — Vision | `AUTOMATED_VERIFIED` | `NOT_STARTED` | Delivered 0.15.0 on 2026-10-13 after explicit advancement/completion authorization while Gate 14 remains pending. Owner image OCR, selected-window text understanding and optional local multimodal adapter: 369 Python tests (43 Vision), 12 frontend/3 Rust tests, 22 evaluations, 39 source/39 frozen/41 installed Vision checks, 16 installed/16 portable native checks, 5 preserving upgrade checks, frozen/source parity and 890-file ZIP integrity pass. General scene-model quality and human UI acceptance remain unverified. See docs/operations/wave-15-report.md. |
| 16 — Computer Use | `AUTOMATED_VERIFIED` | `NOT_STARTED` | Paired release 0.17.0 completed on 2026-10-17 under the user's 2026-10-15 authorization. Explicit owner standard-Win32 See/Plan/Act/Verify; source, frozen and installed native-fixture QA passed. Supported-control scope and pending human gates are recorded in docs/operations/waves-16-17-report.md. |
| 17 — Installer/Updates/Portability | `AUTOMATED_VERIFIED` | `NOT_STARTED` | Paired release 0.17.0 built, installed and packaged on 2026-10-17. Guided pinned setup, managed update/rollback and encrypted portable restore; final activation, failed migration, rollback, restore, offline handoff and native lifecycle QA passed. Clean VM, completed model download, different hardware and human acceptance remain pending. |
| 18 — Advanced Personal Intelligence | `AUTOMATED_VERIFIED` | `NOT_STARTED` | Delivered in 0.20.0 under the user's combined authorization. Evidence-linked relationships, timeline, goals and inferred routine suggestions pass source/frozen API, browser, backup/migration and packaged lifecycle QA. Human acceptance remains pending; see docs/operations/waves-18-20-report.md. |
| 19 — Fine-Tuning Experiment | `DEFERRED` | `DEFERRED` | Opt-in synthetic behavior dataset, GPU recipe and strict comparison support implemented/tested in 0.20.0. Actual training/promotion deferred: no approved behavior use case, training dataset or validated adapter; base model remains active. |
| 20 — Portfolio Release | `AUTOMATED_VERIFIED` | `NOT_STARTED` | 0.20.0 supplies a fictional demo, scoped note sandbox, measured scripted benchmark dashboard, public documentation, Cyanex licensing and Windows CI configuration. Offline source/model and separate GitHub source packages include a one-click BAT; real CPU model/source relocation and automated QA pass. No publication, clean-VM certification or human acceptance is claimed. |

---

# 29. Codex Build-Wave Prompt Contract

Use this structure when authorizing a Build Wave:

```text
You are implementing Project ADAM.

Read completely before changing code:
1. PROJECT_ADAM_MASTER_SPEC.md
2. PROJECT_ADAM_ROADMAP.md
3. PROJECT_ADAM_EXECUTION_PLAN.md

The Master Spec is the architecture authority.
The Roadmap defines milestone scope and acceptance criteria.
The Execution Plan defines which milestones are authorized together and where you must stop for human validation.

CURRENT AUTHORIZATION:
Implement ONLY Build Wave <N> — <NAME>.

Milestones authorized in this wave:
- <milestone>
- <milestone>
...

Execution rules:
1. Implement milestones sequentially.
2. Before each milestone, inspect its exact Roadmap scope and acceptance criteria.
3. Do not implement later milestones early.
4. Run automated verification for each milestone before moving to the next.
5. Fix failures caused by the current milestone before continuing.
6. Record a checkpoint/result after every milestone.
7. If a CORE-CONTRACT conflict is discovered, stop the affected work and report it rather than silently changing architecture.
8. Keep future functionality as interfaces/placeholders only where the Master Spec requires architectural preparation.
9. Never present placeholders as functional features.
10. Preserve privacy, security, model-independence, observability, recovery, and permission contracts.
11. At the end of the final authorized milestone, run the Build Wave regression suite.
12. Update the Build Wave status to AUTOMATED_VERIFIED only if all required checks pass.
13. Provide exact human-test instructions for the corresponding Human Validation Gate.
14. STOP at that gate. Do not begin the next Build Wave.

Final report must include:
- milestones completed,
- files created/modified,
- migrations/schema changes,
- dependencies added/removed,
- architectural decisions,
- commands executed,
- automated test/type/lint results,
- per-milestone acceptance-criteria results,
- regression results,
- known limitations,
- deferred items,
- human-validation procedure,
- current Build Wave status.
```

---

# 30. Human Gate Result Template

After the user tests a wave, record:

```text
HUMAN VALIDATION GATE <N>

Build Wave:
Version / commit:
Date:
Tester:

Result:
[ ] PASS
[ ] PASS WITH NON-BLOCKING NOTES
[ ] REOPEN
[ ] BLOCKED

Scenarios tested:
- ...

Issues found:
- ID:
  severity:
  description:
  reproduction:
  expected:
  actual:

UX notes:
- ...

Performance notes:
- ...

Privacy/security notes:
- ...

Required fixes before next wave:
- ...

Final status:
HUMAN_VALIDATED / REOPENED / BLOCKED
```

---

# 31. Severity Model for Human-Found Issues

| Severity | Meaning | Can next wave begin? |
|---|---|---|
| `S0 CRITICAL` | Security/privacy/data-loss issue, architecture invariant violated, destructive unsafe behavior. | **No** |
| `S1 HIGH` | Core feature unreliable or materially incorrect; major regression. | **No** |
| `S2 MEDIUM` | Important behavior/UX issue with viable workaround. | Normally no unless explicitly accepted. |
| `S3 LOW` | Cosmetic/minor friction; does not compromise the wave's purpose. | Yes, if documented. |
| `S4 NOTE` | Enhancement idea or future refinement. | Yes. |

A wave with an unresolved S0 or S1 issue cannot be `HUMAN_VALIDATED`.

---

# 32. Regression Rule

Once a Build Wave is Human Validated, future waves must not silently break it.

Before every later Human Validation Gate:

1. run automated regression tests for all previously validated core behavior,
2. smoke-test previously validated user-facing critical paths where practical,
3. report any intentional behavior change,
4. reopen the affected earlier wave if a core promise was broken.

Human validation is cumulative. Passing Gate 10 does not excuse breaking Gate 2 memory behavior.

---

# 33. Architecture Amendment Rule

Implementation will eventually reveal things planning missed. That is normal.

If a real architecture change is required:

1. document the observed problem,
2. identify which Master Spec contract is affected,
3. explain why a local implementation fix is insufficient,
4. propose the smallest compatible architecture amendment,
5. identify migrations/regressions caused by the change,
6. update the Master Spec and Roadmap deliberately,
7. increment the relevant document version,
8. rerun affected validation suites.

Never quietly modify architecture because a library made the planned design inconvenient.

---

# 34. What This Plan Intentionally Does Not Do

This file does not:

- redefine subsystem architecture,
- duplicate every Roadmap acceptance criterion,
- select exact future model versions forever,
- guarantee that experimental milestones will ship,
- authorize Codex to implement everything in one run,
- replace human judgement with automated scores,
- replace automated verification with manual testing.

Its purpose is execution control and meaningful validation timing.

---

# 35. Initial Authorization Recommendation

The first Codex authorization should be:

> **Build Wave 1 — Conversational ADAM Alpha**
>
> Implement Milestones 0.1, 1.0, and 1.1 sequentially. Automated-verification checkpoint after each milestone. Stop after 1.1 and provide Human Validation Gate 1 instructions. Do not begin Milestone 2.0.

This gives the user a meaningful first product slice to test without allowing the implementation to run far enough ahead that foundational behavioral problems become expensive to unwind.

---

# 36. Final Execution Principle

> **Codex may move quickly inside a validated architectural lane. It must stop whenever the next decision requires human judgement rather than automated proof.**

That is the operating model for Project ADAM.
