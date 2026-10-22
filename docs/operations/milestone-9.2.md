# Milestone 9.2 - Model benchmark and migration

Release 0.8.0 adds a bounded local model catalog, benchmark receipts, trial
promotion, finalization and rollback. Profiles declare capabilities; declarations
are never treated as measured quality. Installed managed GGUF files are hashed,
checked for changes, and launched through fixed llama.cpp arguments without a
shell. Only ADAM's own process handle can be stopped. An occupied port is refused;
external adapters merely detach. No model is downloaded by these controls.

A benchmark reserves compute explicitly and runs in disposable synthetic stores:
12 real-model/framework cases with real E5 retrieval, plus 10 scripted adversarial
security cases. Security cases exercise the framework boundary, not the candidate's
resistance to every possible attack. Reports include first-token latency, load or
attach latency, character throughput and token throughput when the runtime exposes
its tokenizer. They include identity/memory continuity hashes and declared cards.
Finite rubrics are a gate, not a comprehensive intelligence score.

Promotion needs passing current and candidate reports, zero critical failures,
matching host and datasets, unchanged configuration and GGUF checksum, reports
under 24 hours old, and each local case within the configured 180-second budget.
Lower context, language coverage or declared tools/reasoning/JSON capability needs
explicit acceptance. Client-submitted pass flags and forged receipts are refused.

The trial changes the active adapter only. Finalization atomically publishes the
saved selection after catalog metadata; an interrupted publication retains the
previous saved selection on restart. A failed load retains the old adapter.
Rollback also works after a candidate error latch when actual resources permit.
Identity and memory are not copied or reset. Previous registered weights remain
available after finalization. Per-store locks and catalog revisions refuse
concurrent control and stale controllers, including repeated stale requests.

Saved selection overrides restored settings and TOML; explicit ADAM_MODEL_URL/ID
environment values apply last. A configuration absent from an existing catalog
enters read-only recovery. Clear conflicting overrides before normal startup.
The PowerShell launcher uses a finalized selection before its legacy -Cpu or
-Uncensored switches. Choose the corresponding registered profile to change it.

Backups capture the active model configuration through Settings, but exclude
catalog, benchmark reports and model weights. Restore preserves that configuration;
install/provide its runtime and re-register other profiles for future migrations.
An external alias cannot attest the underlying weight file. Multi-GPU Vulkan
mapping is not validated here; managed GPU QA covers this PC's single Quadro.

CLI hardware inspection is offline. Profiles/register/benchmark require local
owner authentication; use the live owner developer console for trial/finalize/
rollback. Long HTTP benchmarks still require valid fresh owner authorization at
publication. For longer runs, close the API and use the OS-trusted compute CLI.
