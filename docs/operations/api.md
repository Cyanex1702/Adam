# Wave 4 public interfaces

`adam serve`: loopback FastAPI/WebSocket on port 8765. `adam chat`: terminal through
same Runtime. `adam init`: transactional migration to schema 6. Runtime/package 0.5.0.
Authentication and vault databases each have their own version-1 migration ledger.
Start helpers are development conveniences, not the future installer.

| Interface | Contract |
|---|---|
| GET /health | Public model status and runtime version |
| GET /models | Configured model card, alias checked by health |
| GET /identity | Identity version/digest and deterministic live capabilities |
| POST /chat | text, optional session_id, optional sensitivity, optional knowledge_namespace; terminal EventEnvelope |
| WS /ws/chat | Same request; started, token(s), completed/error |
| GET /sessions | Most recently updated persisted sessions |
| GET /sessions/{id}/history | Successful turns; limit 1â€“500, optional before turn ID; chronological page |
| DELETE /sessions/{id} | Close idle session, preserve history |
| POST /sessions/{id}/resume | Explicitly reopen a persisted session |
| GET /sessions/{id}/working | Working state, extractive summary, last context budget |
| PUT /sessions/{id}/working | Replace validated objective/entities/task_state/instructions |
| GET /memory | query, historical=false, archived=false; owner-filtered records and provenance |
| GET /memory/candidates | Pending unconfirmed candidate inspector |
| DELETE /memory/{id} | Deterministic forget of key family and identifiable support/echo records |

Memory and consolidation commands use POST /chat or terminal text; see gate-2.md.

Wave 5 adds authenticated tool/task routes. Profiles use separate sandboxes/stores.

| Route | Behavior |
|---|---|
| GET /tools | Typed registry and actual sandbox path |
| POST /tools/preview | Strict ToolCall; canonical arguments, digest and preconditions |
| GET /actions, GET /actions/{id} | Durable action records and verified receipts |
| POST /actions/{id}/approve | digest and allow; fresh owner elevation for approval |
| POST /actions/{id}/execute | Execute approved effect; read-only calls need no elevation |
| POST /actions/{id}/undo-preview | New inverse preview with conflict checks |
| GET /tasks, GET /tasks/{id} | Task graphs, states and checkpoints |
| POST /tasks | Validated structured Plan |
| POST /tasks/plan | goal: diagnose DIRECTORY or organize DIRECTORY |
| POST /tasks/{id}/approve | Bind approval to digest; allow=false cancels |
| POST /tasks/{id}/run | Explicit serial execution with fresh owner elevation |
| POST /tasks/{id}/cancel | Persist cancellation; stop between steps |
| POST /tasks/{id}/replan | Bounded replacement after known failure, new approval required |

Tool/task failures return fixed error codes with HTTP 409. An HTTP 200 action response
can contain FAILED or UNCERTAIN; inspect result.status. A task can be FAILED/PAUSED
despite a successful HTTP exchange. Never infer a file effect from HTTP status alone.
Desktop DISPATCHED receipts report requested launch, not observed window success.
See gate-5.md for examples, approval expiration and recovery limitations.
They bypass model generation and commit memory mutation plus receipt atomically. Their
operation receipts are VERIFIED; stored owner claims retain REPORTED/UNCERTAIN status.
Ordinary model answers remain UNCERTAIN with model_generation provenance.

Generation started/completed payloads expose context limit, input-token estimate,
response reserve, dropped turns, summary inclusion, and estimator abstraction. Exact
provider tokenization has a reserve; unavailable tokenizer endpoints use conservative
UTF-8 estimates. Oversized current input/protected instructions fail without truncation.

Validation errors return safe 422 responses without request bodies. Failed chat turns
return structured 503 errors; completed partial output is never fabricated. Credentials
and secret sensitivities are rejected before prompts/storage. Lease loss, changed memory,
provider failures, context overflow, storage failures, and unavailable audit storage
fail explicitly. Sessions have a shared 60-second lease renewed every 20 seconds.
Cancellation releases it; a killed process's lease expires. Idle cache eviction preserves
history. Prepared audit records are mandatory, terminal telemetry best effort.

Configuration precedence remains defaults < TOML (ADAM_CONFIG) < process environment.
ADAM_TEXT_ENABLED controls model text generation. Future capability flags reject activation.
Model templates/tokenization remain in the llama.cpp adapter. Identity packs remain
independent of model weights. Background consolidation interval defaults to 300 seconds.

This remains a loopback alpha. Owner HTTP/WebSocket sessions authenticate using a
locally initialized passphrase; guest/demo sessions use physically separate profiles.
Conversation/source SQLite remains cleartext; vault values are encrypted separately.
No model can execute tools or code. Metadata audit omits prompts,
answers, owner memory contents, credentials, and hidden reasoning. Detailed private traces
are not implemented. Do not expose the service as a shared network application.

## Authentication and vault

Only `/health`, `/docs`, `/openapi.json`, `/auth/login` and `/auth/session` are public.
All other HTTP/WebSocket routes require `Authorization: Bearer TOKEN` or the HttpOnly
SameSite Strict `adam_session` cookie. URL tokens and foreign browser origins are denied.
The Swagger Authorize button accepts the returned token. API bodies cannot assign roles.

| Interface | Contract |
|---|---|
| POST /auth/login | password; owner grant, token and cookie, 30-minute expiry |
| POST /auth/session | mode = guest or demo; fresh separate profile per grant |
| GET /auth/status | Current mode/profile and developer elevation status |
| POST /auth/switch | New mode; owner requires password; old token revoked |
| POST /auth/logout | Revoke session and clear cookie |
| POST /auth/elevate | Owner password again; developer/vault elevation for five minutes |
| GET /developer/traces | Elevated owner; metadata only, last 100 records |
| POST /developer/policy | Elevated owner; deterministic ResourcePolicy explanation |
| GET /vault/status | Elevated owner; backend/enabled/unlocked only |
| POST /vault/unlock | Initialize/unlock; empty password for DPAPI, separate 12+ character password for Fernet |
| POST /vault/lock | Lock this process's vault adapter |
| GET /vault/handles | Handle/purpose metadata; never raw values |
| POST /vault/handles | purpose and secret value; returns opaque secret:// handle |
| DELETE /vault/handles/{identifier} | Delete UUID portion after secret:// |

There is no raw-secret GET or HTTP consumer-registration endpoint. Trusted backend
code registers a consumer and calls `Vault.consume(principal, handle, purpose)`;
only that callback receives a redacted SecretValue with an explicit reveal method.
The caller receives a fixed receipt; callback return values are discarded and errors
are replaced with fixed codes. This is the foundation for Wave 5 tools, not a tool runner.

`vault_enabled=false` disables the vault. `vault_backend="auto"` selects current-user
Windows DPAPI on Windows, otherwise password-encrypted Fernet. Explicit `"fernet"`
uses Argon2id (64 MiB, three passes, four lanes); its key is never stored and it starts
locked after restart. Backend is persisted on initialization; configuration changes
cannot reinterpret an existing vault. DPAPI failures never silently switch to plaintext
or a different backend. Explicit lock applies until unlock/restart; DPAPI can unlock
on the next process start under the same Windows account. Non-Windows DPAPI requests fail.


Wave 3 knowledge interfaces (all local owner operations):

| Interface | Contract |
|---|---|
| POST /knowledge/sources | path, namespace=default, policy metadata; ingest original/version/chunks |
| GET /knowledge/sources | optional namespace; canonical records, policy and last known status |
| POST /knowledge/refresh | optional namespace; hash registered files, mark ACTIVE/STALE/MISSING |
| POST /knowledge/reindex | Refresh all sources; rebuild derived points; 503 if model/index unavailable |
| POST /knowledge/retrieve | query (1–2000 chars), namespace=default, limit=5 (1–10); retrieval inspector |
| POST /knowledge/answer | Same query contract; EVIDENCE/ABSTAIN/CONFLICT, quotes, citations and diagnostics |

Chat text `/ask QUESTION` or an explicit `knowledge_namespace` selects the grounded
path, which produces normal started/token/completed events and saves a tagged receipt.
Other chat uses Qwen and explicit memory commands as before. RAG operates without
calling the generation provider; imported knowledge never creates personal memories.
Raw RAG history is available for inspection but excluded from later ordinary prompts,
rolling owner summaries and consolidation candidates. Resume preserves receipts.

SourcePolicy carries sensitivity, allowed_audiences, subjects, source_actor,
disclosure_owner, trust and replication_policy. This alpha fixes the requester to
owner; clients cannot assert another audience. Only current owner-authorized records
in the requested namespace reach keyword search, vector filtering or evidence context.
Imported content is quoted data and cannot execute instructions or tools. Recognized
credentials and SECRET/NEVER_LLM sources are rejected before indexing.

Evidence exposes citation label, canonical source ID/path/title/hash/version/status,
policy, chunk ID/text/locator, keyword score, semantic score and fusion/rerank score.
RETRIEVED means a canonical quotation, not independently verified truth. Missing/weak
evidence returns UNKNOWN and no answer citations. Sufficiency and field conflicts
are heuristic; no free-form factual synthesis or translation is performed. Inspector
results may include weak nearest neighbors even when the answer correctly abstains.

KnowledgeConfig provides enabled=true, allowed_roots=[cwd], max_file_bytes=32 MiB,
chunk_chars=1000, embedding_dir and embedding_threads=2. Runtime never downloads
models. Explicit scripts/setup-knowledge.ps1 verifies the immutable embedding model.
The local vector store holds a single-process lock; contention/missing model returns
KEYWORD mode with RAG.VECTOR_UNAVAILABLE, while reindex fails explicitly. Index receipts
are tied to source revision, model revision and dimensions. Knowledge changes between
retrieval and a chat receipt commit reject the turn for retry.

## Wave 7 maintenance

All `/maintenance/*` endpoints require an owner grant and fresh owner
reauthentication. Guest/demo and expired elevation are denied. Passphrases use
secret request fields; validation/errors return fixed codes without input values.

| Endpoint | Operation |
|---|---|
| POST /maintenance/backups | `password`, generation daily/weekly/monthly/milestone, include_vault=false |
| GET /maintenance/backups | Managed archive metadata; unverified until unlocked |
| POST /maintenance/backups/{id}/verify | `password`; authenticated archive, manifest and schema verification |
| GET /maintenance/backups/{id}/download | Encrypted archive bytes |
| POST /maintenance/backups/{id}/restore | `password`, restore_vault=false; fresh isolated UUID directory |
| GET /maintenance/integrity | Read-only core store/identity/settings inspection |
| POST /maintenance/exports | Optional sections, formats, person, project, since, until, memory_type, conversation_id, task_id, max_records |
| GET /maintenance/exports/{id}/{filename} | Fixed names data.json, data.jsonl, summary.md, records.csv, export-manifest.json |

Export defaults include all five sections and four formats; receipts report
counts, section status, omissions, checksums and target. Outputs are cleartext
owner data; store/download them accordingly. Knowledge export includes metadata,
not full document bodies. A malformed filter returns sanitized INPUT.INVALID.
Archive/restore/export failures return HTTP 409 with a fixed maintenance code.

Startup integrity faults replace the normal API with a read-only recovery app:
GET /health returns RECOVERY_READ_ONLY and fixed diagnostic codes; other routes
return 503. No private inspection is exposed over HTTP in that state. Use the
local maintenance CLI for OS-trusted inspection, partial export and fresh restore.
Close ADAM before offline index rebuild or recovery inspection of active WAL data.
See [Gate 7](gate-7.md) for filters, passphrase/vault requirements and purge scope.

CLI: `python -m adam.cli ingest "PATH" --namespace NAME`, `sources`, `refresh`,
`retrieve "QUESTION"`, `ask "QUESTION"`, `reindex`. Terminal adds `/namespace NAME`,
`/ingest "PATH"`, `/sources`, `/refresh`, `/inspect QUESTION`, `/reindex`, `/ask QUESTION`.
Detailed walkthrough: docs/operations/gate-3.md.

Canonical policy, versions and source revision are captured in one SQLite read snapshot.
The answer limit bounds ordinary excerpts; detected competing values remain visible
even when that requires extra citations (up to the ten retrieved candidates).

## Compute and model management (0.8.0)

All /developer endpoints require owner login and fresh elevation. Fixed compute
failures return HTTP 409; invalid input returns sanitized 422. No client can submit
its own gate results.

| Endpoint | Behavior |
|---|---|
| GET /developer/hardware?benchmark=true | Offline profile, optional CPU hashing benchmark |
| GET /developer/compute | Lifecycle, measured resources, pressure, queue and capabilities |
| POST /developer/compute/load | Explicit attach/load and cooldown recovery |
| POST /developer/compute/unload | Owned process stop or external adapter detach |
| GET /developer/models | Registered declared cards, active/default/trial/previous and report IDs |
| POST /developer/models | ModelProfile JSON; bounded installed GGUF basename or local external adapter |
| POST /developer/models/{id}/benchmark | Exclusive real-model/E5 local gate and scripted security gate |
| POST /developer/models/{id}/promote | benchmark_id, acknowledge_reduced=false; begin process-local trial |
| POST /developer/models/finalize | Commit passing trial as saved default |
| POST /developer/models/rollback | Return to previous registered model |

POST load/unload/benchmark/finalize/rollback accept an empty JSON object. Identity
includes compute_capabilities. CLI: python -m adam.compute.cli hardware --benchmark,
profiles, register PROFILE_JSON_PATH, benchmark PROFILE_ID; optional --data-dir
precedes the command. Model mutation commands require hidden owner authentication.
See [Gate 8](gate-8.md) and [migration](milestone-9.2.md) for persistence and limits.
