# Milestone 1.0 checkpoint

2026-10-05. 13 foundation/runtime tests pass. Ruff lint/format and strict mypy
(15 source files) pass. Local Vulkan inference returned `17 times 23 is 391.`
through Runtime with correct model metadata and structured completion.
First request measured 19.18 seconds including prompt processing; no latency target claimed.

llama.cpp b11146; Qwen3-4B-Instruct-2507 Abliterated Q4_K_M, 4096 context,
3 CPU threads, GPU layer offload, 768 output tokens. Download checksum verified.
The user requested a smaller, preferably uncensored model for i5 6th gen/16 GB/M4000.
Qwen3-8B remains the reference configuration in `adam.example.toml`.

Start a loopback llama.cpp server with the model alias matching TOML, then:
`scripts/dev.ps1 -Command chat` for terminal chat or `scripts/dev.ps1` for the API.
The helper picks up local `adam.local.toml`; otherwise set `ADAM_CONFIG` explicitly.
POST `/chat`, GET `/health`, GET `/models`, DELETE `/sessions/{id}`, WS `/ws/chat`.
Streams use the canonical EventEnvelope: started, token, completed/error.

Verified: offline startup without a model; streaming Unicode; configuration swap;
malformed/truncated/unavailable provider failures; context overflow; cancellation;
RAM-only sessions; validation redaction; hostile Host rejected; metadata-only traces.
No migrations after schema 1. No tools, persistence, voice, RAG, or remote access.
