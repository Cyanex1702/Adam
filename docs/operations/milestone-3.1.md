# Milestone 3.1

Automated verified: local Qdrant plus offline CPU multilingual E5 (384 dimensions), BM25 keyword ranking and reciprocal-rank fusion. Owner policy and current namespace/chunk IDs filter retrieval before evidence context construction. Immutable model revision and SHA-256 checks precede inference; runtime performs no network downloads. Two embedding CPU threads, batches of two, no extra GPU model.

51 tests, Ruff and strict mypy passed. Real embedding recall@5: 10/10 over 20 synthetic sources, including Roman Urdu and Urdu; target 90%. Rebuild, restart, permission exclusion and missing-model keyword fallback tested. Evidence includes actual source ID, path, hash, revision, chunk ID and exact locator.

Local Qdrant allows one process per index path; concurrent processes fall back to keyword search with a diagnostic. Indexes are derived and rebuildable; raw blobs and SQLite versions are preserved. Source changes rebuild the small local index; large corpus incremental indexing is future optimization.

Model: [multilingual E5 small](https://huggingface.co/intfloat/multilingual-e5-small). Vector API: [Qdrant client](https://python-client.qdrant.tech/).
