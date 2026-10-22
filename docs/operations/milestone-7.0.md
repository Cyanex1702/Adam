# Milestone 7.0 — Developer trace console

Verified with 106 regressions and strict mypy. Protected metadata APIs expose
timeline, latency stages, model/context counters, memory/RAG evidence IDs, task
graph checkpoints, tool/permission receipts and a health/resource dashboard.
The local /console page logs in and reauthenticates the owner using an HTTP-only
session cookie. Credentials are never saved in browser storage. The console
renders data using text nodes and a restrictive content security policy.
Unknown VRAM is explicitly unavailable; process RAM is measured on Windows.

SQLite traces have schema 1, configurable OFF/ERROR/NORMAL/DEBUG/TRACE level,
7-day default retention and a 10,000-event cap. All levels retain only metadata;
no hidden reasoning, prompts, document/file content or tool arguments are traced.
Legacy turn receipts remain available in a bounded 1,000-line JSONL file.
Inspector APIs require fresh authenticated owner developer mode. Phase durations
can overlap; first-token latency is included in generation, not added to it.
