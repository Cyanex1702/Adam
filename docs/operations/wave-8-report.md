# Wave 8 - Hardware and brain intelligence

Completed milestones 9.0, 9.1 and 9.2 on 2026-10-07. Source and installed runtime
are **0.8.0** at `%PROJECT_ROOT%`.
Status: `AUTOMATED_VERIFIED`; Gate 8 awaits human validation. Wave 9 has not started.
The user's next-job request accepted Wave 7 and authorized this wave. The supplied
planning documents define requirements; they do not authorize later waves.

ADAM now profiles hardware offline, exposes measured resources and declared model
capabilities, pauses work under pressure, manages owned model processes, and gates
model changes through benchmark, trial, finalize and rollback. Identity and memory
stay in their existing stores across a model change.

| Validation | Result |
|---|---|
| Full regression suite | 186 passed |
| Ruff lint and format | Passed |
| Strict mypy | Passed, 70 backend source files |
| Full scripted evaluation/security gate | 22 passed, zero critical failures |
| Real current model + E5 gate | 12 local and 10 scripted security cases passed |
| Real candidate model + E5 gate | 12 local and 10 scripted security cases passed |
| Live Vulkan migration/lifecycle QA | 38 checks passed |
| Browser controls QA | 9 observations passed |
| Prior maintenance HTTP/terminal regression | 37 checks passed |
| Prior action/task/terminal regression | 33 checks passed |
| Installed package and application version | Both 0.8.0 |

Real QA used the installed Qwen3-4B Instruct and abliteration GGUFs on the Quadro
M4000's 8 GiB VRAM, with E5 on CPU. Both passed the same finite gate. A 2048-context
candidate required explicit reduction acceptance. Trials preserved the old saved
default, recalled the retained preference, rolled back, finalized persistently,
unloaded/reloaded, then rolled back the finalized selection. Guest management was
denied. The owned model process stopped at shutdown. No personal owner store was
modified and no model was downloaded.

The first live attempt did not pass every quality rubric with a 256-token reply
budget. The saved passing run uses 768 tokens; gates were not weakened. Windows
Store public-asset path resolution was repaired after a startup failure. Actual
system RAM varied substantially; this disposable QA profile used a 98% ceiling
and the unchanged 512 MiB floor. Production remains at 94%. Browser UI fixtures
injected headroom and are explicitly separate from real-model evidence.

| Short counting probe | Current | Candidate |
|---|---|---|
| First token | 2.87 s | 2.82 s |
| Total generation | 5.30 s | 5.22 s |
| Runtime-tokenized output | 62 tokens | 62 tokens |
| Throughput after first token | 25.5 tokens/s | 25.8 tokens/s |

These short-probe numbers are not general conversation speed guarantees. Telemetry
reports ADAM process RSS separately from system RAM; it does not aggregate every
external server's RAM. Hardware detection alone does not certify GPU execution.
Unknown sensor values remain null; internet reachability is never probed.

Fault tests cover pressure and unavailable GPU measurements, OOM/cooldown,
queue capacity/cancellation including repeated cancellation, pressure after queue
wait, active-turn lifecycle refusal, foreign port protection, invalid GGUF/path,
failed restore, bad/tampered/stale/noncomparable evidence, concurrent/stale catalog
control, reduced capability acceptance, configuration recovery and interrupted
finalization. Existing guest contexts follow a shared provider swap without
exposing the owner store. One warning is the installed Starlette TestClient/httpx
deprecation.

Checkpoint commits: milestone 9.0 `08a281b`, milestone 9.1 `644c3cc`; the final
Wave 8 checkpoint contains milestone 9.2, QA and documentation. No existing schema
migration checksum or Master Spec architecture contract changed.

Evidence: [hardware](evidence/wave8-hardware.json),
[current benchmark](evidence/wave8-current-benchmark.json),
[candidate benchmark](evidence/wave8-candidate-benchmark.json),
[live migration QA](evidence/wave8-live-qa.json),
[browser QA](evidence/wave8-browser-qa.json),
[maintenance regression](evidence/wave8-maintenance-regression.json),
[action regression](evidence/wave8-actions-regression.json),
[scripted gate](evidence/wave8-full-eval.json).

Reproduce with `scripts/check.ps1` and `scripts/qa-wave8.py`; the latter needs the
already installed runtime, two GGUFs and E5, free loopback ports and memory headroom.
See [Gate 8](gate-8.md) for human validation and [migration details](milestone-9.2.md)
for backup exclusions, selection precedence, external aliases and operating limits.
