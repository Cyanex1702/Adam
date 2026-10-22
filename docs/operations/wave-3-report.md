# Wave 3 implementation report

Completed milestones 3.0, 3.1 and 3.2 in order, with an automated checkpoint after
each. Runtime/package 0.3.0, database schema 6. Wave 2 acceptance was recorded from
the user's request to begin Wave 3. Wave 3 is AUTOMATED_VERIFIED; Gate 3 remains pending.

Implemented:

- Versioned, permission-scoped source registry with immutable originals, content
  hashes, duplicate identity, registered aliases, namespaces and currentness checks.
- UTF-8 text/Markdown, code and text PDF ingestion, exact chunk locators, bounded files,
  root checks and credential rejection before parsing and storage.
- Offline CPU embeddings, local Qdrant vectors, BM25 keyword search, reciprocal-rank
  fusion, permission and namespace filtering before retrieval/context construction.
- Replaceable reranker interface, evidence sufficiency, extractive grounded answers,
  structured-field conflict detection, source citations and retrieval inspector.
- API/terminal integration and persisted RAG receipts, separated from ordinary chat
  context, owner summaries and personal-memory candidate extraction.

Evidence:

| Verification | Result |
|---|---|
| Unit/regression suite | 56 passed; Ruff lint/format and strict mypy pass |
| Real E5/Qdrant retrieval | Recall@5 10/10 over 20 synthetic sources; declared target 90% |
| Real grounded-answer evaluation | 19/19: supported queries, 7 missing-answer cases, conflict and multiple sources |
| Live loopback API | 25 assertions passed, including real restart and graceful shutdown |
| Real terminal/start helper | 8 checks passed across restart/resume |
| Existing Qwen behavior | 7/7 Wave 1 smoke scenarios passed |
| Default database | Backed up and migrated 5 â†’ 6; row counts preserved (empty default turns/memories) |

JSON evidence is in `docs/operations/evidence/wave3-*.json`. The finite synthetic
evaluation is a baseline, not a general accuracy claim. Unsupported **generated**
factual claims are zero because the grounded path emits source quotations; this does
not prove the original documents are correct or that each excerpt answers every aspect.

Hardware measurement on the user's machine: a warm API answer took 74.4 ms. The actual
API Python process with E5/Qdrant loaded used 843 MiB working set, with 955.8 MiB peak
and 948.4 MiB private memory. Qwen and Codex are excluded. Measurements cover a small
synthetic corpus and vary with documents, other processes and cold startup.

Embedding model: [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small),
immutable revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, 384 dimensions. Direct
ONNX Runtime CPU inference uses two threads, batches of two, query/passage prefixes,
masked mean pooling and normalization. No PyTorch or additional GPU model is loaded.
Model/tokenizer files total 487,351,240 bytes and are SHA-256 verified before inference.
Setup downloads are explicit; normal queries are offline. Vector implementation uses
the [Qdrant Python client](https://github.com/qdrant/qdrant-client).

Windows Qdrant 1.19.1 collection deletion retained SQLite handles during a real test.
Rebuilds now clear points through the public API and repopulate the collection, with
model/dimension-specific collection names. Directory-rename and actual-process restart
checks verify handle release. Canonical source data is never deleted by reindexing.

Limits: grounded answers quote sources rather than generate new prose, aggregate
numbers or translate them. Sufficiency is heuristic; field conflicts do not cover all
semantic contradictions. Cross-language queries passed the listed Urdu/Roman Urdu
examples; broader language coverage is unproven. Scanned PDFs/OCR, full filesystem
watching, large-corpus incremental indexing, guest authentication, tools, voice and
later waves are not implemented. Currentness is checked at retrieval/commit boundaries;
an OS file edit cannot be atomically locked with a database transaction.

Start with `scripts\start.ps1` and follow `docs/operations/gate-3.md`. The embedding
model is installed on this machine. Synthetic validation data is isolated from normal
runtime data. Test API processes were shut down; the existing user model server was
reused and left running. No Wave 4 work has begun.

Canonical reads are atomic across source policies, versions, chunks and revision.
A regression test mutates a source during embedding and verifies the old evidence
is rejected. A limit-of-one conflict test verifies both competing values remain cited.


Startup repair after the owner's Gate 3 attempt: normal PowerShell lacked qdrant-client
although Codex's redirected environment had it. The helper now checks all locked
packages, runtime imports and the editable source location before starting; it repairs
missing/outdated dependencies in the selected environment and verifies installation.
Existing environments are not recreated by -Install. Model setup runs dependency
verification first. Public E5 assets can be reused from the Codex Store cache when the
normal model location is missing; runtime data remains in the configured data directory,
and model SHA-256 checks still apply.

57 regression tests and static checks pass. A fresh environment was bootstrapped,
then qdrant-client was deliberately removed from that isolated environment. Startup
detected/reinstalled it, opened the terminal successfully, and the second startup
needed no installation. See evidence/wave3-startup-repair.json. This corrects the earlier
verification gap; Gate 3 still requires the owner's ordinary PowerShell test.
