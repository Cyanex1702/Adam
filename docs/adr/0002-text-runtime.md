# ADR 0002: local text brain

llama.cpp is an externally managed loopback-only server. Adapter owns wire formatting.
Metadata comes from configuration; live alias is checked against `/v1/models` every turn.
Load attaches; unload does not kill the server. Proxies and redirects are disabled.

Sessions are RAM-only, capped, serialized per session, and keep eight recent turns.
Conservative UTF-8 byte context estimates fail closed. No summaries or persistence yet.
Only completed turns enter history. Truncation fails visibly with incomplete partial text.
Trace files contain operational metadata only: no prompts, responses, or hidden reasoning.
The API binds loopback, validates Host, and denies foreign WebSocket Origins.

Protocol: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
