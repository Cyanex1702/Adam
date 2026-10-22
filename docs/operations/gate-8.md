# Gate 8 - Hardware and brain intelligence

Wave 8 implements milestones 9.0–9.2 in the PC project. Human validation is pending.
Run only command lines inside code blocks in PowerShell.

```powershell
Set-Location -LiteralPath '%PROJECT_ROOT%'
$pythonExe = & "$env:LOCALAPPDATA\ADAM\dev-env\Scripts\python.exe" -c 'import os,sys; print(os.path.realpath(sys.executable))'
& $pythonExe -m adam.compute.cli hardware --benchmark
.\scripts\start.ps1 -Api
```

Open http://127.0.0.1:8765/console and unlock with the existing owner passphrase.
Configure the passphrase first with /auth-init in the owner terminal if necessary.

1. Inspect hardware: this PC should show i5-6500, about 16 GB RAM, Quadro M4000
   with 8 GiB VRAM, Windows and data-volume storage. Missing sensors are null.
   Detection alone says DETECTED_NOT_RUNTIME_VERIFIED; the saved live QA report
   separately records actual Vulkan generation. CPU hashing is not an LLM score.
2. Inspect compute resources and the capability envelope during a normal reply.
   Text, explicit memory commands and approved tools are distinct capabilities.
   Voice/vision are unavailable; reasoning and model tools are declared, untested
   capabilities unless evaluated separately. Default RAM ceiling is 94%, with
   512 MiB available RAM, 128 MiB disk and optional 256 MiB VRAM floors.
3. Unload and reload. A legacy launcher-owned server is external to this manager:
   unload detaches and does not terminate that process. A registered managed
   profile stops only its own process. Busy live turns block lifecycle changes.
4. Register a candidate using the JSON form. For an already installed model,
   adapt this profile to a free loopback port and the desired capability card:

```json
{"profile_id":"compact_candidate","managed":true,"model_file":"qwen3-4b-abliterated.gguf","device":"vulkan","model":{"model_id":"qwen3-4b-abliterated","display_name":"Compact candidate","base_url":"http://127.0.0.1:8081","context_limit":4096,"max_tokens":768,"temperature":0.1}}
```

5. Benchmark current, then the candidate profile. Wait for complete reports.
   A failed gate keeps the default unchanged. Registration alone grants no
   promotion approval. Benchmarking reserves compute and may temporarily evict
   owned weights. External servers remain running and share RAM/VRAM; if the
   resource budget refuses another instance, free resources before retrying.
   External rollback also requires its original server to be available.
   Do not start another model instance on the same port.
6. Enter the candidate profile ID and its returned benchmark ID, acknowledge any
   declared reduction, and begin a trial. Recall a harmless saved preference;
   confirm identity and memory survive. The saved default must remain current.
7. Roll back and verify the old card and preference. Repeat the trial, finalize
   and restart to verify persistence. Roll back the finalized selection if desired.
8. Lock the console. Panels and model inputs must clear; guest requests cannot
   access model management. OOM/repeated transport errors latch a visible ERROR;
   after cooldown and freeing resources, explicitly reload. No automatic restart
   loop is installed. Low-priority background work pauses under pressure and
   yields to queued interactive work at safe operation boundaries.

Automated fault tests cover RAM/disk/VRAM pressure, missing GPU sensors, OOM,
queue limits/timeouts/cancellation, worker completion, stale and concurrent
controllers, bad/tampered/stale proofs, failed model loads, unsafe paths, port
collisions and interrupted finalization. Avoid deliberately exhausting the PC.

The live QA helper uses a disposable 98% RAM ceiling with the same 512 MiB floor
because other applications consumed much of this machine's RAM. Production stays
at 94%. Free memory before benchmarking if admission pauses. Do not alter safety
policy merely to force a promotion. CPU fallback is an explicit profile choice.

See [migration details](milestone-9.2.md) for selection precedence, long-run
reauthentication, backup exclusions and external alias limits. Automated evidence
and the test inventory are in [Wave 8 report](wave-8-report.md). Wave 9 awaits
acceptance of this gate.
