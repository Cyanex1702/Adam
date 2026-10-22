# Milestone 7.1 — Evaluation harness v1

Verified: 110 regression tests, Ruff lint/format and strict mypy. The isolated
12-scenario suite covers golden conversation rubrics, memory recall, RAG evidence
and abstention, tool selection, task verification and secret ingress. Machine
reports contain case IDs, scores, timings, error classifications and trace IDs;
failed answers/private diagnostics are never echoed. Fixtures are replayable by
CLI or protected developer API. Baselines are keyed by release and model metadata;
comparisons reject mismatched fixture digests or execution modes.

Default probes test the framework, not model quality. --real-model uses the
configured loopback model; --real-rag enables installed public E5 assets. Every
scenario uses temporary synthetic data. Owner stores and actions are never replayed.
The harness found an older SQLite migration connection leak on Windows; migration
transactions now close their handles without altering migration SQL/checksums.
