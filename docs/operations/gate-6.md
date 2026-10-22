# Gate 6 - Observable and Evaluated ADAM

Active PC source: `%PROJECT_ROOT%`.
Run these commands in PowerShell:

```powershell
Set-Location -LiteralPath '%PROJECT_ROOT%'
.\scripts\start.ps1 -Api
```

Open http://127.0.0.1:8765/console. Use the owner passphrase you already configured.
If none exists, initialize it once with `/auth-init` in the normal ADAM terminal.
Developer access requires owner login and fresh reauthentication and expires after
five minutes. Guest/demo cannot unlock it. Closing the start session stops the API
and any model process that the start helper owns.

1. Unlock the console. Confirm configured Qwen metadata, subsystem health and
   measured API-process RAM. VRAM is explicitly unavailable. CPU count describes
   capacity; RAM does not include the separate llama-server process.
2. Send a short chat using `/chat` in the authenticated API docs, then Refresh.
   Click its trace ID. Inspect session, memory, context, model and completion
   stages. First-token and generation durations overlap and should not be summed.
3. Inspect a memory query and an ingested knowledge query. Evidence contains IDs,
   retrieval scores and status; private memory values and document text are omitted.
4. Use the Gate 5 preview/approve/execute flow for a synthetic sandbox note. Refresh
   to see PREVIEW, APPROVED, RUNNING and VERIFIED. For a `/plan` task, paste its
   actual task UUID into the task inspector to inspect dependencies and receipts.
5. Select `task_verify`, then Replay. Confirm passed. Replay uses a new synthetic
   store and does not rerun your personal task or create files in your sandbox.
   Repeat with `encoded_exfiltration` and `trace_secrecy`.
6. Lock and log out. Confirm evidence disappears and the passphrase is cleared.
   Returning to developer endpoints requires fresh owner authentication again.

Run the automated gate in another PowerShell session:

```powershell
.\scripts\check.ps1
```

To reproduce real-model and E5 QA while the model is running on port 8080:

```powershell
$pythonExe = & "$env:LOCALAPPDATA\ADAM\dev-env\Scripts\python.exe" -c 'import os,sys; print(os.path.realpath(sys.executable))'
& $pythonExe scripts\qa-wave6.py
```

This uses temporary synthetic stores and a separate ephemeral loopback API port.
It requires the installed compact Qwen/E5 setup and downloads nothing. It updates
Wave 6 QA reports. A failed check exits nonzero.

For a machine-readable release/model baseline and comparison:

```powershell
& $pythonExe -m adam.evals.runner --suite full --output .\outputs\eval.json --baseline-dir .\outputs\baselines
& $pythonExe -m adam.evals.runner --suite full --compare .\outputs\eval.json --summary
```

Default probes validate framework behavior. Add `--real-model --real-rag` to use
configured Qwen and E5. Comparisons require matching fixture digests and execution
modes. Real-model evaluation has finite substring rubrics and needs your judgment.

Tracing defaults to NORMAL, seven days and at most 10,000 SQLite events. Configure
`[tracing]` with `level`, `retention_days` and `max_events` in an explicit TOML file;
levels are OFF, ERROR, NORMAL, DEBUG and TRACE. No level records hidden reasoning
or chat bodies. The compatibility JSONL audit is independently bounded to 1,000
lines. Retention cleanup is not forensic secure erasure.

Wave 6 is AUTOMATED_VERIFIED. Human validation remains pending; Wave 7 has not begun.
