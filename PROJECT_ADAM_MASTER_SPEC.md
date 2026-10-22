# PROJECT ADAM — MASTER ENGINEERING SPECIFICATION

**Document:** `PROJECT_ADAM_MASTER_SPEC.md`  
**Architecture baseline:** v0.1  
**Status:** Pre-implementation architecture freeze candidate  
**Project name:** ADAM  
**Working interpretation of name:** optional / branding decision deferred  
**Primary objective:** Build a local-first, voice-first, model-agnostic personal AI runtime whose identity, memory, privacy, tools, and history survive model and device changes.

---

## 0. How to Read This Specification

Feature tags:

- **[CORE-CONTRACT]** — must be designed correctly before implementation because later changes would be expensive or dangerous.
- **[V1]** — implemented in the first serious usable release.
- **[LATER]** — architecture must support it now; implementation comes later.
- **[EXPERIMENTAL]** — optional research area; no core feature may depend on it.

Priority rules:

1. Security and privacy override convenience.
2. Deterministic authorization overrides model preference.
3. Evidence and verification override fluent model claims.
4. User data is portable and model-independent.
5. ADAM remains useful in degraded/offline modes.
6. New capabilities must plug into defined interfaces rather than bypass them.

Architecture change rule:

> After architecture freeze, any change to a **[CORE-CONTRACT]** requires an explicit architecture amendment describing the motivation, compatibility impact, migration plan, and tests.

---

# 1. Vision

ADAM is not a chatbot and is not the currently installed LLM.

ADAM is a persistent personal AI runtime composed of:

- identity and personality,
- truthfulness / epistemic policy,
- lifelong memory,
- personal knowledge and RAG,
- privacy and trust enforcement,
- authentication and authorization,
- agent and task orchestration,
- tool execution,
- device routing,
- voice and real-time conversation,
- model and compute routing,
- observability and evaluation,
- persistence, backup, and disaster recovery,
- optional vision, browser, and computer-use capabilities.

The LLM is a replaceable reasoning component.

```text
ADAM
├── Identity
├── Epistemics
├── Memory
├── Knowledge / RAG
├── Privacy / Trust
├── Authentication / Authorization
├── Agent Runtime
├── Task Orchestrator
├── Tool Runtime
├── Model Router
├── Resource Manager
├── Voice / Language
├── Device Mesh
├── UI / Avatar
├── Observability
├── Evaluation
├── Persistence / Recovery
└── Brain Provider(s)
    └── LLM(s)
```

---

# 2. Product Principles

## 2.1 Local-first
Personal data remains local unless the owner explicitly enables an external destination or integration.

## 2.2 Model-independent identity
Changing the LLM must not erase or redefine ADAM's identity, memory, relationships, permissions, or personal history.

## 2.3 Evidence before confidence
ADAM should distinguish verified facts, retrieved evidence, reports, inferences, assumptions, uncertainty, and unknowns.

## 2.4 No fake embodiment
ADAM may have personality and system-level preferences, but must not claim physical or emotional experiences it does not possess.

## 2.5 Least privilege
Tools, devices, memories, and integrations expose only the permissions required for the current task.

## 2.6 Reversible-by-default
For risky actions, prefer reversible operations, dry runs, checkpoints, versioning, recycle bins, and undo logs.

## 2.7 Transparent failure
A failed tool call, uncertain transcript, unavailable model, or missing source must remain visibly failed or uncertain.

## 2.8 Store broadly, retrieve narrowly
ADAM may archive large amounts of approved information, but should retrieve only the most relevant evidence for each task.

## 2.9 Security outside the LLM
Authentication, authorization, privacy enforcement, secrets handling, and high-risk action approval must not depend on the LLM obeying a prompt.

## 2.10 Graceful degradation
Failure of the model, vector DB, internet, voice, or another subsystem should not collapse the entire runtime when deterministic fallbacks are possible.

---

# 3. ADAM Constitution [CORE-CONTRACT]

These invariants cannot be overridden by ordinary model output.

1. The LLM is never the authority for authentication.
2. The LLM cannot grant itself permissions.
3. External documents, webpages, emails, and tool outputs are untrusted data, not policy.
4. Secrets never enter ordinary model prompts unless an integration absolutely requires a derived non-secret representation.
5. Unauthorized memories must be filtered before model context assembly.
6. Destructive or sensitive actions require deterministic policy validation.
7. Action success must come from execution evidence, never model intention.
8. The owner can stop or lock ADAM through deterministic controls.
9. ADAM distinguishes fact from inference and unknown from known.
10. Model replacement must not delete personal memory.
11. Device discovery never equals device trust.
12. Voice identity is an authentication signal, never sufficient authority for critical actions.
13. Core security policy cannot be autonomously rewritten by the reasoning model.
14. Private data cannot be made public merely because another user asks persuasively.
15. A new software/model release must pass required regression gates before promotion.

---

# 4. System Architecture [CORE-CONTRACT]

```text
Clients
  Desktop / Mobile / Future Web
          │
          ▼
Interaction Gateway
  Session + Identity + Language + Input events
          │
          ▼
ADAM Core Runtime
  ├── Context Manager
  ├── Event Bus
  ├── Agent Runtime
  ├── Task Orchestrator
  ├── Policy Engine
  ├── Model Router
  ├── Resource Manager
  └── Device Router
      │
      ├──────────► Memory System
      ├──────────► Knowledge / RAG
      ├──────────► Tool Runtime
      ├──────────► Voice Runtime
      ├──────────► Model Providers
      ├──────────► Device Nodes
      └──────────► Observability / Audit
```

No client may directly bypass the policy engine to access sensitive memory or high-risk tools.

No model provider may directly execute privileged tools.

---

# 5. Reference Technology Stack

This stack is a starting implementation target, not an architectural dependency.

| Area | Initial choice |
|---|---|
| Core language | Python |
| API | FastAPI |
| Realtime transport | WebSocket |
| Agent orchestration | LangGraph behind ADAM interfaces |
| Desktop/mobile shell | Tauri 2 + React + TypeScript |
| Local LLM runtime | llama.cpp provider |
| Optional dev runtime | Ollama adapter |
| Initial text model | Qwen3-8B quantized local model |
| Structured store | SQLite initially |
| Vector store | Qdrant local |
| Embeddings | local embedding provider |
| VAD | Silero VAD adapter |
| STT | faster-whisper adapter |
| TTS | Kokoro adapter initially |
| Audio processing | provider interface; WebRTC/RNNoise-class processing candidate |
| UI 3D/avatar | Three.js / React Three Fiber |
| Testing | pytest + frontend tests + scenario eval runner |
| Packaging | Tauri + Python service packaging |
| Containers | optional for services/sandboxes |
| Secrets | OS secure storage + encrypted ADAM vault |
| Trace format | structured local events/traces |

Framework adapters must isolate framework-specific behavior.

---

# 6. Identity and Personality [CORE-CONTRACT]

ADAM identity lives outside model weights.

Suggested structure:

```text
identity/
├── identity.yaml
├── personality.yaml
├── communication.yaml
├── epistemics.yaml
├── privacy_defaults.yaml
├── terminology.yaml
├── pronunciation.yaml
└── versions/
```

Identity Pack contains:

- name and self-description,
- role relative to owner,
- communication style,
- humor and formality preferences,
- response verbosity defaults,
- tool-use philosophy,
- privacy philosophy,
- uncertainty behavior,
- supported identity claims,
- prohibited fake embodiment claims,
- terminology and aliases,
- pronunciation overrides.

Identity Pack is versioned.

A model swap must load the same identity pack and then pass personality/behavior regression tests.

---

# 7. Truthfulness and Epistemics [CORE-CONTRACT]

ADAM classifies knowledge internally:

```text
VERIFIED
RETRIEVED
REPORTED
INFERRED
ASSUMED
UNCERTAIN
UNKNOWN
```

Examples:

- Owner explicitly states a preference -> `REPORTED`, high trust.
- Live filesystem tool confirms a path -> `VERIFIED`.
- A trusted document contains a claim -> `RETRIEVED`.
- ADAM concludes preference from project usage -> `INFERRED`.
- Missing evidence -> `UNKNOWN`.

Rules:

- Personality must never hide uncertainty.
- Personal facts should not be guessed when unknown.
- Important claims should retain provenance.
- High-risk actions cannot rely on low-confidence intent interpretation.
- ADAM may express configured/system preferences, but not fabricated sensory experience.

Example:

Bad:
> "Pizza is my favorite food."

Acceptable:
> "I do not eat, so I do not have a literal favorite food."

---

# 8. User, Speaker, and Session Identity [CORE-CONTRACT]

Roles:

```text
PUBLIC
GUEST
KNOWN_PERSON
TRUSTED_PERSON
OWNER
ADMIN
ELEVATED_ADMIN
```

Roles are not sufficient by themselves. Authorization evaluates:

- authenticated person,
- device trust,
- current session,
- capability,
- resource sensitivity,
- context,
- elevation state.

Voice identity is advisory.

Sensitive access may require:

- trusted device possession,
- OS biometric/passkey,
- hardware key,
- explicit reauthentication.

Speaker recognition returns identity + confidence, never just a name.

```json
{
  "speaker_id": "owner",
  "confidence": 0.94,
  "method": ["voice_embedding", "active_device_session"]
}
```

Low identity confidence reduces authority.

---

# 9. Privacy and Trust Engine [CORE-CONTRACT]

Every protected memory/knowledge item supports metadata such as:

```json
{
  "subject_ids": ["owner"],
  "source_actor": "owner",
  "sensitivity": "PRIVATE",
  "allowed_audiences": ["owner"],
  "disclosure_owner": "owner",
  "confidence": 0.99,
  "provenance": "conversation:...",
  "replication_policy": "trusted_devices"
}
```

Sensitivity classes:

```text
PUBLIC
PERSONAL
PRIVATE
CONFIDENTIAL
SECRET
SYSTEM_SECRET
NEVER_LLM
```

Disclosure pipeline:

```text
Request
  ↓
Resolve requester identity
  ↓
Resolve resource sensitivity / disclosure owner
  ↓
Policy check
  ↓
Filter unauthorized evidence
  ↓
Only then construct model context
```

The model should not receive information it is forbidden to disclose.

Social confidentiality:

Information supplied by another person can remain restricted even if it concerns the owner.

ADAM tracks:

- who supplied information,
- who the information concerns,
- who controls disclosure,
- whether confidentiality was requested.

---

# 10. Demo / Guest Isolation [CORE-CONTRACT]

Portfolio demonstrations must not rely solely on filtering the owner's real data.

Provide a distinct sanitized namespace/profile:

```text
profiles/
├── owner/
└── demo/
```

Demo mode may include:

- synthetic memories,
- sample projects,
- safe tools,
- public portfolio data,
- fake calendar/inbox data.

Demo mode cannot query real owner-only stores.

---

# 11. Language and Communication Engine [CORE-CONTRACT]

ADAM is multilingual by architecture.

Each utterance may include:

```json
{
  "primary_language": "ur",
  "detected_languages": ["ur", "en"],
  "code_switching": true,
  "raw_text": "...",
  "normalized_semantics": "..."
}
```

Requirements:

- multilingual text input/output,
- code-switching within a sentence,
- Romanized-language handling,
- per-speaker language preference,
- translation fallback only when needed,
- cross-language memory retrieval,
- technical terminology preservation,
- pronunciation dictionary,
- language-aware TTS.

Memory is not trapped in the language in which it was created.

Original wording should be preserved when useful while semantic fields enable multilingual retrieval.

---

# 12. Conversation and Turn-Taking Engine [CORE-CONTRACT]

Turn end must not be based on silence alone.

Inputs may include:

- voice activity,
- silence length,
- grammatical/semantic completeness,
- filler words,
- prosody,
- speaker-specific pause profile,
- current conversation state,
- interruption words,
- confidence.

Output:

```json
{
  "turn_end_probability": 0.82,
  "recommended_action": "WAIT|LISTEN|TAKE_TURN",
  "reason_codes": ["LINGUISTICALLY_INCOMPLETE"]
}
```

Default behavior:

- prefer a small delay over cutting users off,
- learn a speaker's normal pause style gradually,
- remain quiet during ambiguous short pauses,
- optional minimal conversational acknowledgement only when appropriate,
- unfinished sentence strongly biases toward waiting.

Interruption classes:

```text
ACKNOWLEDGEMENT
HARD_INTERRUPT
CORRECTION
NEW_REQUEST
BACKGROUND_SPEECH
UNCERTAIN
```

Examples:

- "mhm" -> usually continue speaking.
- "stop" -> cancel TTS immediately.
- "actually open the other project" -> interrupt and replace request.
- unrelated background talk -> ignore where possible.

---

# 13. Multi-Speaker and Spatial Audio [LATER]

Pipeline:

```text
Audio
→ source separation
→ diarization
→ speaker recognition
→ direction estimate (if hardware supports)
→ per-speaker utterances
→ authorization / conversation routing
```

ADAM must not merge overlapping speakers into one authoritative command.

If three speakers issue requests simultaneously:

- preserve speaker attribution,
- prioritize authorization and interaction context,
- queue independent low-risk conversational requests,
- reject unauthorized actions,
- explicitly acknowledge uncertainty if separation is poor.

Spatial audio is optional and hardware-dependent. Fields exist before implementation and may remain `null`.

---

# 14. Voice and Real-Time Audio Runtime [LATER, architecture now]

Target pipeline:

```text
Microphone
→ echo cancellation
→ gain control
→ noise suppression
→ VAD
→ speaker processing
→ multilingual STT
→ transcript confidence
→ contextual transcript repair
→ turn-taking
→ agent
→ streaming response chunks
→ TTS
→ speaker
```

Raw transcript and repaired transcript remain distinguishable.

```json
{
  "raw_transcript": "open my rag pro... from last...",
  "repaired_transcript": "Open my RAG project from last week.",
  "repair_confidence": 0.88
}
```

For sensitive actions, low raw confidence cannot be hidden by aggressive transcript repair.

Default raw-audio retention: **off** after processing unless explicitly enabled.

---

# 15. Short-Term / Working Memory [CORE-CONTRACT]

Working memory contains only information necessary for the current task/session:

- recent turns,
- current objective,
- active entities,
- pending approvals,
- tool outputs still relevant,
- task state,
- rolling summary.

Do not insert entire chat histories into context.

Context pressure handling:

- summarize old turns,
- remove stale tool outputs,
- preserve critical instructions,
- archive raw transcript separately.

---

# 16. Lifelong Memory Architecture [CORE-CONTRACT]

Memory layers:

```text
RAW LIFETIME ARCHIVE
    ↓
EPISODIC MEMORY
SEMANTIC MEMORY
PREFERENCES
RELATIONSHIPS
GOALS
PROJECT MEMORY
TIMELINE
    ↓
HOT / WARM / COLD retrieval tiers
```

Suggested memory fields:

```json
{
  "memory_id": "...",
  "content": "...",
  "type": "preference",
  "subjects": ["owner"],
  "source": "conversation:...",
  "epistemic_status": "REPORTED",
  "confidence": 0.96,
  "importance": 0.82,
  "privacy": "PERSONAL",
  "created_at": "...",
  "valid_from": "...",
  "valid_until": null,
  "status": "CURRENT",
  "pinned": false,
  "last_accessed": "...",
  "access_count": 0
}
```

Rules:

- age lowers retrieval priority but does not automatically delete meaningful information,
- pinned memories cannot be auto-pruned,
- outdated facts become historical rather than disappearing,
- contradictions are represented temporally,
- raw archive and active memory are separate,
- important results are consolidated; trivial details remain archival or expire per policy.

---

# 17. Memory Confidence and Contradictions [CORE-CONTRACT]

Memory classifications include:

```text
FACT
PREFERENCE
BELIEF
POSSIBILITY
TEMPORARY_STATE
INTENTION
OPINION
INFERENCE
```

Example:

"I may switch to Linux" cannot become "User uses Linux."

Contradictions should preserve timeline:

```text
VS Code
valid 2024-2028
status HISTORICAL

Cursor
valid 2028-present
status CURRENT
```

Evidence precedence guideline:

```text
live system state
> explicit owner statement
> trusted records
> historical memory
> inference
```

This is context-dependent and must not be blindly globalized to all domains.

---

# 18. Memory Lifecycle and Consolidation [CORE-CONTRACT]

Memory retention classes:

```text
PINNED
PERMANENT
LONG_TERM
TEMPORARY
SESSION_ONLY
EXPIRING
ARCHIVAL
```

Background consolidation may:

- deduplicate,
- merge synonymous memories,
- update project summaries,
- identify important events,
- resolve temporal state,
- reduce retrieval priority,
- archive low-value detail.

Default rule:

> Reduce retrieval priority before deletion.

User commands:

- "Remember this."
- "Remember this permanently."
- "That is wrong."
- "Forget that."
- "Show what you remember about X."
- "Why do you know that?"

These must become first-class operations.

---

# 19. Personal Knowledge Graph [LATER]

Use relational/graph-like links without requiring a dedicated graph database initially.

Entities:

- people,
- projects,
- organizations,
- devices,
- files,
- goals,
- events,
- locations,
- concepts.

Relations:

```text
owner → works_on → Project ADAM
Project ADAM → uses → Qwen
Person A → collaborates_on → Project X
```

Graph data inherits privacy and provenance.

---

# 20. Knowledge and RAG [CORE-CONTRACT, V1 later milestone]

Memory and external knowledge remain distinct.

Examples:

- "I prefer Python" -> memory.
- "This PDF says X" -> knowledge.

Ingestion pipeline:

```text
Source
→ parser
→ metadata
→ deduplication
→ chunking
→ embedding
→ index
```

Retrieval pipeline:

```text
Query
→ metadata filters
→ keyword retrieval
→ vector retrieval
→ hybrid merge
→ rerank
→ evidence selection
→ context assembly
```

Requirements:

- keep original sources,
- embeddings/indexes are rebuildable,
- source citations,
- freshness detection,
- file move/rename/delete handling,
- project namespaces,
- code-specific chunking,
- trust classification,
- permission filtering before retrieval.

RAG retrieves evidence, not unquestionable truth.

---

# 21. External Web Knowledge [LATER]

Live web content is:

```text
EXTERNAL
UNTRUSTED
TIME-SENSITIVE
```

Web results must retain:

- URL/source,
- retrieval time,
- source type,
- trust/reputation metadata if available,
- quoted/extracted evidence.

Web content may inform reasoning but never grant permissions or rewrite system policy.

---

# 22. Agent Runtime [CORE-CONTRACT]

Requests are classified:

```text
DIRECT
RETRIEVAL
SINGLE_ACTION
MULTI_STEP
BACKGROUND_TASK
SCHEDULED_TASK
CONDITION_TASK
CRITICAL_TASK
```

Not every request enters heavyweight agent mode.

Reasoning profiles:

```text
FAST
DELIBERATE
DEEP_TASK
```

Reasoning profile affects planning depth, verification, and compute budget.

---

# 23. Tool Runtime [CORE-CONTRACT]

Tools expose explicit schemas, not unrestricted system access.

Example tool metadata:

```json
{
  "name": "filesystem.search",
  "risk_level": 1,
  "reversible": false,
  "required_capability": "filesystem.read",
  "supported_devices": ["desktop"],
  "arguments_schema": {}
}
```

Initial safe tools may include:

```text
get_system_info
search_files
read_file
open_file
open_application
create_note
retrieve_memory
search_knowledge
```

No unrestricted shell in V1.

---

# 24. Tool Risk and Permission Model [CORE-CONTRACT]

Suggested risk scale:

| Risk | Meaning | Example |
|---|---|---|
| 0 | observation | current time / CPU usage |
| 1 | read-only | search file |
| 2 | benign local action | open app |
| 3 | creates state | create note |
| 4 | modifies existing data | edit/move file |
| 5 | destructive/sensitive | delete/send external message |
| 6 | critical | credential/financial/mass destructive action |

Authorization considers:

```text
identity
device
scope
risk
resource
current elevation
reversibility
context
```

Permissions are scope-aware:

```text
allow read D:/Projects/**
allow write D:/Projects/ADAM/**
deny D:/Personal/**
deny C:/Windows/**
```

The model cannot modify permission policy directly.

---

# 25. Dry-Run, Undo, and Transactions [CORE-CONTRACT]

For high-impact operations:

```text
PLAN
→ SIMULATE
→ SHOW EFFECT
→ AUTHORIZE
→ EXECUTE
→ VERIFY
```

Reversible operations produce action-journal entries.

Prefer:

- recycle bin over permanent deletion,
- version snapshot before document edit,
- transaction/checkpoint before bulk reorganization.

"Undo that" should resolve the most recent compatible reversible action.

---

# 26. Sandboxed Code and Terminal Execution [LATER]

Generated code runs in isolation with:

- time limit,
- memory limit,
- CPU limit,
- restricted filesystem,
- network policy,
- captured stdout/stderr,
- explicit mounted directories.

The main ADAM runtime never directly `exec`s arbitrary model-generated code.

---

# 27. Planning and Task Orchestration [CORE-CONTRACT]

A task is a persistent structured object.

```json
{
  "task_id": "...",
  "goal": "...",
  "status": "RUNNING",
  "priority": "INTERACTIVE",
  "steps": [],
  "created_by": "owner",
  "created_at": "..."
}
```

Step fields may include:

- objective,
- dependencies,
- required capability,
- assigned device,
- model profile,
- risk,
- expected result,
- verification method,
- timeout,
- retry strategy,
- status.

States:

```text
CREATED
PLANNING
WAITING
RUNNING
PAUSED
WAITING_FOR_PERMISSION
WAITING_FOR_RESOURCE
VERIFYING
COMPLETED
PARTIALLY_COMPLETED
FAILED
CANCELLED
```

Planner, executor, and verifier are separate roles/interfaces.

---

# 28. Replanning and Task Safety [CORE-CONTRACT]

Plans are mutable when reality changes.

```text
unexpected state
→ pause dependent steps
→ update state
→ replan
```

Each task has:

- retry budget,
- replan budget,
- time budget,
- compute budget.

Clarification threshold is based on both uncertainty and consequence.

High uncertainty + high consequence -> ask.

Task execution must never equate "requested" with "completed."

---

# 29. Task Persistence and Idempotency [CORE-CONTRACT]

Tasks checkpoint between meaningful steps.

After crash/restart:

- detect interrupted task,
- identify completed actions,
- identify uncertain in-flight action,
- avoid duplicate external side effects.

Critical remote/tool actions use execution IDs.

Example:

```text
action_id = ...
already completed? -> do not repeat
```

---

# 30. Model Provider Architecture [CORE-CONTRACT]

Interface concept:

```python
class ModelProvider:
    generate(...)
    stream(...)
    supports_tools()
    supports_reasoning()
    supports_json()
    get_context_limit()
    count_tokens(...)
    get_capabilities()
    health_check()
    load()
    unload()
```

Providers:

```text
LlamaCppProvider
OllamaProvider (optional)
FutureProvider
```

Model-specific formatting belongs in provider/adapter code, never in ADAM identity.

---

# 31. Model Registry and Capability Cards [CORE-CONTRACT]

Each installed model records:

- modality,
- context,
- tool support,
- reasoning support,
- language support,
- observed performance,
- memory footprint,
- hardware compatibility,
- evaluation scorecard,
- provider/runtime,
- quantization.

ADAM benchmarks models on ADAM tasks, not only public leaderboard scores.

---

# 32. Model Routing [CORE-CONTRACT]

Routing inputs:

- task complexity,
- modality,
- latency requirement,
- privacy requirement,
- context requirement,
- current hardware load,
- model capability,
- resource availability.

Potential routes:

```text
simple conversation -> fast text model
complex analysis -> strongest available reasoner
image -> vision model
speech -> STT model
TTS -> voice model
RAG -> embedding/rerank models
```

V1 may use one text model while preserving the routing contract.

---

# 33. Hardware and Resource Intelligence [CORE-CONTRACT]

Hardware profiler records:

- CPU,
- RAM,
- GPU(s),
- VRAM,
- storage,
- OS,
- relevant acceleration support,
- network state.

Initial benchmark profile may include:

- model load speed,
- token generation rate,
- prompt processing,
- STT speed,
- TTS latency,
- embedding throughput,
- disk performance.

ADAM stores observed machine-specific performance.

---

# 34. Resource Manager [CORE-CONTRACT]

Tracks:

- loaded models,
- VRAM/RAM use,
- CPU load,
- GPU load,
- storage pressure,
- temperatures when available,
- battery when relevant,
- active tasks.

Model lifecycle:

```text
NOT_INSTALLED
DOWNLOADING
AVAILABLE
LOADING
LOADED
ACTIVE
IDLE
UNLOADING
ERROR
```

Priority classes:

```text
CRITICAL
INTERACTIVE
HIGH
NORMAL
LOW
IDLE
```

Interactive conversation preempts background indexing where safe.

---

# 35. Capability Degradation [CORE-CONTRACT]

ADAM must report its current capability envelope.

Example:

```text
text              AVAILABLE
memory            AVAILABLE
tools             AVAILABLE
voice             DEGRADED
vision            UNAVAILABLE
deep_reasoning    REDUCED
```

It may recommend a compatible model for the hardware, but installation/promotion remains controlled.

No fake emotional framing of reduced compute.

---

# 36. Context Budget Manager [CORE-CONTRACT]

Model context is dynamically allocated among:

- identity/policy,
- recent conversation,
- working memory,
- retrieved long-term memory,
- RAG evidence,
- tool results,
- task state,
- response reserve.

When near limit:

- summarize old turns,
- compress stale tool output,
- reduce redundant evidence,
- preserve security and current task requirements.

---

# 37. Device Mesh [CORE-CONTRACT]

ADAM is one identity across multiple nodes.

Node roles may include:

```text
CORE_NODE
MODEL_NODE
TOOL_NODE
CLIENT_NODE
SENSOR_NODE
```

A device may have multiple roles.

Device registry records:

- device ID,
- public key,
- trust level,
- app/protocol version,
- capabilities,
- health,
- last seen,
- revocation status.

---

# 38. Secure Device Pairing [CORE-CONTRACT]

Pairing flow:

```text
new device
→ pairing QR/code
→ cryptographic key exchange
→ owner confirmation on trusted device
→ capability policy assignment
→ device registered
```

Discovery is not authentication.

Revoked device keys are rejected.

Remote wipe is optional defense-in-depth, not a primary control.

---

# 39. Device Capability Routing [CORE-CONTRACT]

Example:

```text
phone request: search PC files
→ capability required: filesystem.search
→ phone lacks capability
→ desktop node provides capability
→ execute on desktop
→ return signed result
```

Routing considers:

- capability,
- device online state,
- privacy policy,
- network latency,
- current load,
- sensitivity.

---

# 40. Multi-Device Data Sync [CORE-CONTRACT]

Initial rule:

> One authoritative ADAM core at a time.

Clients may cache approved subsets.

Synchronization should prefer event/version-based state rather than copying a live database file.

Data supports replication policies:

```text
CORE_ONLY
TRUSTED_DEVICES
OWNER_DEVICES
ALL_APPROVED
```

Conflicts use:

- version IDs,
- source,
- timestamps,
- event ordering,
- temporal memory logic.

---

# 41. Offline and Remote Modes [LATER]

LAN mode:
- low-latency,
- local network,
- no internet dependency where possible.

Remote mode:
- encrypted authenticated channel,
- never expose raw local API unauthenticated to the internet,
- remote policies may be stricter.

Offline mobile mode may expose:
- cached profile,
- selected memory,
- reminders,
- local notes,
- optional small local model.

---

# 42. Session Handoff [LATER]

Conversation/task handoff transfers:

- active conversation context,
- working memory,
- current task ID,
- relevant pending approvals.

Only one device is primary voice output for a session unless explicitly configured otherwise.

---

# 43. Notifications, Scheduling, and Proactivity [LATER]

Scheduler supports:

```text
ONE_TIME
RECURRING
CONDITION_WATCH
BACKGROUND
```

Notification routing supports:

- active device,
- desktop,
- mobile,
- voice,
- priority.

Proactive behavior is opt-in and policy-bound.

ADAM may surface useful state, but must not become an uncontrolled surveillance/reminder engine.

Proactive suggestions should have a clear trigger and user value.

---

# 44. Avatar and Visual State [LATER]

Initial avatar target: abstract shader/orb/core, not a realistic human face.

States:

```text
IDLE
LISTENING
UNDERSTANDING
THINKING
SEARCHING
USING_TOOL
WAITING_FOR_PERMISSION
SPEAKING
UNCERTAIN
ERROR
OFFLINE
```

Speaking animation uses actual TTS audio analysis.

Avatar expresses operational state, not claims of emotion.

---

# 45. Vision and Screen Understanding [LATER]

Vision joins through perception interfaces.

Sources:

- phone camera,
- desktop screenshot,
- uploaded image,
- document image.

Perception events include source device and privacy metadata.

Vision model does not directly click or execute.

Computer-use pipeline:

```text
SEE
→ INTERPRET
→ PLAN
→ POLICY CHECK
→ ACT
→ VERIFY
```

---

# 46. Browser and Computer Use [LATER]

Browser/computer automation is a tool provider, not direct model control.

Capabilities are explicit:

- open URL,
- navigate,
- click,
- type,
- read page,
- download,
- upload.

Sensitive browser actions require risk evaluation.

External page text remains untrusted.

---

# 47. Integrations / MCP / Plugins [LATER]

ADAM core supports external tool providers.

Concept:

```text
ToolProvider
├── BuiltInProvider
├── DeviceProvider
├── MCPProvider
├── GitHubProvider
├── CalendarProvider
├── EmailProvider
└── FutureProvider
```

The registry discovers capability metadata rather than hard-coding integrations into model prompts.

---

# 48. Secrets Management [CORE-CONTRACT]

Secrets use a separate encrypted vault / OS secure storage.

Examples:

- API keys,
- OAuth refresh tokens,
- device private keys,
- integration credentials.

Ordinary memory stores references/handles, not raw secrets.

Tools obtain secrets through a privileged secrets interface.

Secrets are `NEVER_LOG`.

---

# 49. Event Bus [CORE-CONTRACT]

Canonical event envelope:

```json
{
  "event_id": "...",
  "event_type": "tool.completed",
  "timestamp": "...",
  "trace_id": "...",
  "session_id": "...",
  "task_id": null,
  "actor_id": "owner",
  "device_id": "desktop_01",
  "sensitivity": "INTERNAL",
  "payload": {}
}
```

Core event families:

```text
session.*
identity.*
voice.*
stt.*
language.*
agent.*
memory.*
knowledge.*
rag.*
task.*
tool.*
policy.*
auth.*
model.*
resource.*
device.*
tts.*
avatar.*
notification.*
backup.*
eval.*
system.*
```

Events decouple UI/avatar/voice from internal components.

---

# 50. Observability and Developer Mode [CORE-CONTRACT]

Every significant interaction has a trace ID.

Store:

- decisions,
- evidence references,
- retrieval results,
- tool requests/results,
- permission results,
- model metadata,
- latency,
- resource use,
- task transitions,
- errors.

Do not store hidden chain-of-thought.

Developer mode may show:

- event timeline,
- model/context usage,
- memory candidates,
- RAG ranking,
- task graph,
- tool trace,
- health,
- VRAM/RAM,
- latency breakdown.

Normal mode shows simplified human-readable state.

---

# 51. Logging and Privacy [CORE-CONTRACT]

Sensitivity:

```text
PUBLIC
INTERNAL
PRIVATE
SECRET
NEVER_LOG
```

Credentials/private keys are never logged.

Private traces require authenticated developer mode.

Trace levels:

```text
OFF
ERROR
NORMAL
DEBUG
TRACE
```

Detailed trace retention is configurable and shorter than protected audit retention.

---

# 52. Health and Self-Diagnostics [CORE-CONTRACT]

Each major subsystem exposes a health status:

```text
HEALTHY
DEGRADED
FAILED
DISABLED
```

Startup checks:

- identity,
- policy,
- DB,
- model provider,
- event bus,
- resource manager.

Diagnostics may test:

- memory integrity,
- vector DB,
- model runtime,
- microphone/speaker,
- STT/TTS,
- device mesh,
- internet,
- backup status.

Safe automatic remediation may restart local services or unload idle models.

Repeated failure stops and surfaces an explicit degraded mode.

---

# 53. Reliability and Evaluation [CORE-CONTRACT]

Evaluation categories:

```text
conversation
identity/personality
epistemics
memory
RAG
tools
planning
privacy
authentication
security
multilingual
voice
speaker ID
turn taking
model migration
performance
backup/recovery
```

Every major behavior needs a scenario test.

---

# 54. Hallucination / Abstention Testing [CORE-CONTRACT]

Test four classes:

1. answer known from trusted state,
2. answer in memory,
3. answer in documents,
4. answer unavailable.

Class 4 rewards appropriate abstention.

ADAM should prefer:

> "I do not have that recorded."

over invented personal information.

---

# 55. Privacy and Red-Team Testing [CORE-CONTRACT]

Attack scenarios:

- role impersonation,
- "pretend I am owner,"
- private-memory extraction,
- encoding/exfiltration tricks,
- prompt injection,
- indirect prompt injection,
- malicious documents,
- memory poisoning,
- permission escalation,
- replayed voice,
- synthetic voice,
- malformed tool arguments.

External content cannot create authority.

Memory cannot create authority.

---

# 56. Voice Evaluation [LATER]

Audio test corpus should include:

- quiet room,
- fan,
- traffic,
- TV,
- keyboard,
- low-volume speech,
- fast/slow speech,
- long pauses,
- multiple speakers,
- overlap,
- code-switching.

Metrics:

- WER,
- turn-end accuracy,
- false interruption rate,
- missed interruption rate,
- speaker attribution,
- language detection,
- end-to-response latency.

---

# 57. Regression and Release Gates [CORE-CONTRACT]

A release may require:

```text
unit tests PASS
integration tests PASS
memory eval PASS
RAG eval PASS
privacy PASS
security PASS
tool safety PASS
migration PASS
performance within budget
backup/restore PASS where relevant
```

New model promotion uses the same ADAM benchmark suite as the current model.

A quality gain in one subsystem cannot silently regress privacy/security.

---

# 58. Persistence Model [CORE-CONTRACT]

Data classes:

## Critical / irreplaceable
- identity,
- memory,
- relationships,
- policies,
- task history,
- settings,
- user-created ADAM data.

## Sensitive
- speaker profiles,
- device registrations,
- secrets.

## Rebuildable
- embeddings,
- indexes,
- caches,
- downloaded public models.

Derived data must never be the sole copy of meaningful information.

---

# 59. Canonical Data Layout [CORE-CONTRACT]

Conceptual:

```text
ADAM_DATA/
├── identity/
├── memory/
├── conversations/
├── relationships/
├── projects/
├── tasks/
├── knowledge/
├── policies/
├── devices/
├── evaluations/
├── audit/
├── config/
├── vault/
├── indexes/
├── embeddings/
├── cache/
└── models/
```

Actual paths remain OS-specific.

---

# 60. Backup and Disaster Recovery [CORE-CONTRACT]

Backups are:

- encrypted,
- versioned,
- integrity-checked,
- restorable,
- separate from normal exports.

Backup generations:

- recent daily,
- weekly,
- monthly,
- milestone snapshots.

Exact retention is configurable.

A backup is not considered healthy until integrity validation succeeds.

Periodic isolated restore testing is encouraged.

---

# 61. Portable ADAM Package [LATER]

A portable package contains:

```text
manifest
identity
memory
relationships
project state
conversation archive
policies
tasks
knowledge metadata
settings
checksums
schema versions
```

Models and vector indexes do not need to be included unless user chooses.

Restoration onto new hardware:

```text
restore identity/data
→ detect hardware
→ choose compatible brain
→ rebuild indexes
→ run regression checks
→ resume
```

---

# 62. Export and User Data Ownership [CORE-CONTRACT]

Human-readable export formats should include:

- JSON/JSONL,
- Markdown where useful,
- CSV for tabular records,
- optional SQLite snapshot.

Selective exports:

- project,
- person,
- date range,
- memory type,
- conversation,
- task.

"Backup" and "export" are distinct concepts.

---

# 63. Secure Deletion [CORE-CONTRACT]

"Forget this" and "permanently purge this" are different operations.

Purge policy must define whether data is removed from:

- active memory,
- archives,
- future backups,
- existing backup generations,
- indexes.

UI must make scope explicit.

---

# 64. Recovery Mode [CORE-CONTRACT]

If integrity fails:

```text
RECOVERY MODE
```

Permitted:

- inspect,
- export,
- diagnostics,
- restore backup.

Blocked:

- risky writes,
- destructive tools,
- schema migration unless explicitly entered,
- autonomous consolidation.

---

# 65. Update and Rollback System [LATER]

Channels:

```text
STABLE
BETA
DEVELOPMENT
```

Update flow:

```text
pre-update snapshot
→ compatibility check
→ migrate
→ health checks
→ regression subset
→ commit
```

Failure -> rollback.

ADAM core/security policy cannot be rewritten by a model without explicit software update/owner approval.

---

# 66. Configuration Profiles [CORE-CONTRACT]

Profiles may include:

```text
OWNER
GUEST
DEMO
PRIVATE
OFFLINE
LOW_POWER
TRAVEL
DEVELOPER
RECOVERY
```

Profiles alter policy/configuration, not core invariants.

---

# 67. Feature Flags [CORE-CONTRACT]

Example:

```yaml
features:
  voice: false
  speaker_id: false
  spatial_audio: false
  vision: false
  browser_control: false
  proactive_mode: false
  mobile_mesh: false
```

Experimental features default off.

---

# 68. Performance Budgets

Initial targets are provisional and must be tuned on real hardware.

Suggested starting goals:

| Interaction | Target |
|---|---|
| Local memory lookup | < 300 ms typical |
| Simple deterministic tool dispatch | < 500 ms typical |
| Text first token | < 2 s where hardware permits |
| Voice response start | < 2-3 s initial V1; improve later |
| UI/avatar | 60 FPS on target desktop |
| Turn-taking false cut-off | lower priority than small extra delay |
| Crash-safe state commit | transactional |

Accuracy/security targets override latency for sensitive actions.

---

# 69. Storage Strategy

SQLite initially stores:

- sessions,
- structured memory,
- tasks,
- device metadata,
- audit metadata,
- configuration metadata.

Qdrant stores vector representations / retrieval metadata.

Raw source files remain separate from vectors.

Large archives may move to cold storage later.

Memory capacity is not limited by LLM context size. Retrieval remains selective.

---

# 70. Core API Boundaries [CORE-CONTRACT]

Suggested internal service interfaces:

```text
IdentityService
AuthService
PolicyService
MemoryService
KnowledgeService
AgentService
TaskService
ToolRegistry
ToolExecutor
ModelRegistry
ModelRouter
ResourceManager
DeviceRegistry
DeviceRouter
VoiceService
LanguageService
EventBus
TraceService
BackupService
EvaluationService
```

No component may directly reach through another component's storage unless defined as an internal migration/admin operation.

---

# 71. Repository Architecture

Recommended monorepo:

```text
adam/
├── apps/
│   ├── desktop/
│   ├── mobile/
│   └── demo/
├── backend/
│   ├── api/
│   ├── core/
│   ├── identity/
│   ├── auth/
│   ├── policy/
│   ├── agent/
│   ├── tasks/
│   ├── memory/
│   ├── knowledge/
│   ├── rag/
│   ├── tools/
│   ├── models/
│   ├── resources/
│   ├── devices/
│   ├── voice/
│   ├── language/
│   ├── events/
│   ├── observability/
│   ├── backup/
│   └── evals/
├── identity/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   ├── scenarios/
│   └── fixtures/
├── docs/
│   ├── architecture/
│   ├── adr/
│   └── operations/
├── scripts/
├── packaging/
└── README.md
```

Do not create empty future-module forests purely to look impressive. Create directories as their milestone begins, while preserving the documented boundaries.

---

# 72. Coding and Architecture Standards

1. Typed interfaces for core domain objects.
2. Structured errors, not anonymous exceptions at boundaries.
3. No tool side effect without a trace/action ID.
4. No direct secrets access outside vault interface.
5. No model-specific code in domain services.
6. No UI dependency inside backend core.
7. No policy decisions inside frontend-only code.
8. Tests accompany every [CORE-CONTRACT] implementation.
9. Database migrations are explicit and reversible where practical.
10. New tool must declare risk, scope, reversibility, and permission requirements.

---

# 73. Failure Taxonomy

Examples:

```text
MODEL.OUT_OF_MEMORY
MODEL.UNAVAILABLE
MEMORY.RETRIEVAL.EMPTY
MEMORY.CONFLICT
RAG.INDEX_UNAVAILABLE
TOOL.PERMISSION_DENIED
TOOL.EXECUTION.TIMEOUT
AUTH.IDENTITY_UNCERTAIN
VOICE.STT.LOW_CONFIDENCE
DEVICE.NODE_OFFLINE
DATABASE.INTEGRITY_FAILURE
RESOURCE.GPU_PRESSURE
NETWORK.REMOTE_UNREACHABLE
```

Each structured error may specify:

- severity,
- retryability,
- fallback,
- user-safe explanation,
- developer details,
- correlation/trace ID.

---

# 74. Degraded-Mode Matrix

Examples:

| Failed subsystem | Fallback |
|---|---|
| LLM | deterministic tools + retrieval + explicit limited mode |
| Vector DB | keyword/metadata search |
| TTS | text only |
| STT | text input |
| Internet | local-only |
| GPU | CPU/smaller model if configured |
| Remote node | local capabilities only |
| Knowledge index rebuilding | keyword fallback |
| Primary DB integrity issue | recovery/read-only mode |

---

# 75. Security Threat Model Summary

Primary threats:

- unauthorized local user,
- stolen device,
- voice replay / cloning,
- malicious webpage/document/email,
- prompt injection,
- malicious or compromised plugin,
- model hallucination,
- accidental destructive tool call,
- secret leakage in logs/prompts,
- backup theft,
- device impersonation,
- corrupted data/index,
- compromised remote channel.

Mitigations must live in deterministic system layers.

---

# 76. Portfolio / Demo Requirements

ADAM should eventually demonstrate:

- local model inference,
- model abstraction,
- RAG,
- vector search,
- persistent memory,
- temporal memory,
- agent/tool use,
- permissions,
- LangGraph orchestration,
- voice,
- multilingual behavior,
- model/hardware benchmarking,
- observability,
- evaluation,
- red teaming,
- backup/recovery,
- multi-device design.

Developer dashboard should make the engineering visible without exposing private data.

---

# 77. Explicit Non-Goals for Early Releases

Do not begin with:

- realistic humanoid avatar,
- unrestricted shell,
- autonomous financial actions,
- always-on camera,
- unbounded self-modification,
- multi-agent swarm architecture,
- training an LLM from scratch,
- full phone/desktop control,
- constant passive surveillance,
- cloud dependency,
- mandatory fine-tuning.

---

# 78. Fine-Tuning Position [EXPERIMENTAL]

Personal facts remain outside weights.

Fine-tuning, if later used, targets:

- response behavior,
- tool-selection style,
- structured output consistency,
- specialized domain behavior.

Use adapter-based training such as LoRA/QLoRA rather than retraining to store personal memory.

Any candidate fine-tuned model must pass the same migration/evaluation gates.

---

# 79. Initial V1 Definition

The first serious V1 target is:

> A fully local text-first ADAM running on the owner's PC, using a replaceable local model provider, persistent identity and memory, personal RAG, safe tools, privacy-aware authorization, structured tasks, observability, and evaluation.

V1 may not yet include:

- full streaming voice,
- speaker recognition,
- mobile mesh,
- vision,
- computer use,
- spatial audio,
- proactive automation.

---

# 80. Architecture Freeze Checklist

Before implementation:

- [ ] Master spec reviewed.
- [ ] Milestone roadmap accepted.
- [ ] ADAM Constitution accepted.
- [ ] Core domain schemas accepted.
- [ ] Event envelope accepted.
- [ ] ModelProvider contract accepted.
- [ ] Tool contract accepted.
- [ ] Memory contract accepted.
- [ ] Policy/privacy metadata accepted.
- [ ] Task state model accepted.
- [ ] Error envelope accepted.
- [ ] Data directory strategy accepted.
- [ ] Versioning / migration policy accepted.
- [ ] Milestone 1 scope explicitly excludes future features.

---

# 81. Definition of "ADAM"

The final architectural identity is:

> **ADAM is a persistent, local-first, model-agnostic personal AI runtime that combines identity, memory, knowledge, privacy, tools, devices, perception, reasoning, and reliable task execution. Models provide reasoning capacity; they do not define ADAM's identity.**

This definition should remain stable across model generations and hardware changes.
