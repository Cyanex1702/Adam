# Gate 7 - Resilient ADAM

Wave 7 implements milestones 8.0–8.2 in the PC project at
`%PROJECT_ROOT%`. Human validation is pending.
Use a new test directory for every restore/export. These operations never replace
an existing directory. Copy only the commands inside code blocks into PowerShell.

```powershell
Set-Location -LiteralPath '%PROJECT_ROOT%'
$pythonExe = & "$env:LOCALAPPDATA\ADAM\dev-env\Scripts\python.exe" -c 'import os,sys; print(os.path.realpath(sys.executable))'
```

1. In the normal ADAM terminal, remember a harmless preference such as
   `/remember preference backup demo = before snapshot`. Configure an owner
   passphrase with `/auth-init` if you have not already done so, then close ADAM.
2. Create a milestone backup. Enter your owner passphrase, then a separate backup
   passphrase at the hidden prompts. Keep that backup passphrase separately;
   ADAM does not save it and cannot recover it.

```powershell
& $pythonExe -m adam.resilience.cli backup --generation milestone
```

The receipt supplies the archive path. Replace the example below with that actual
path. Verify it once correctly and once using a wrong passphrase. The latter must
report `BACKUP.AUTHENTICATION_FAILED` and exit nonzero.

```powershell
$archive = 'C:\REPLACE\actual-milestone-backup.adambak'
& $pythonExe -m adam.resilience.cli verify $archive
```

3. Restart ADAM, change the preference to `after snapshot`, then close ADAM. Restore
   the archive to a fresh test directory, without the vault. No LLM is needed.

```powershell
$restored = Join-Path $env:LOCALAPPDATA 'ADAM-Gate7-Restore'
& $pythonExe -m adam.resilience.cli restore $archive $restored
& $pythonExe -m adam.resilience.cli --data-dir $restored recovery
```

If that directory already exists, choose a new name. Verify reports `HEALTHY`.
The command is still a read-only inspection session. Saved identity and settings
live under the restored directory; model weights are excluded from archives.

4. Inspect the restored preference and export it. Normal export asks for the owner
   passphrase restored from the archive. Read `data.json`, `data.jsonl`, `summary.md`,
   `records.csv` and `export-manifest.json` in the new output directory. Confirm
   the older preference, timestamps and provenance survive.

```powershell
& $pythonExe -m adam.resilience.cli --data-dir $restored recovery --table memories
$exported = Join-Path $env:LOCALAPPDATA 'ADAM-Gate7-Export'
& $pythonExe -m adam.resilience.cli --data-dir $restored export $exported --memory-type preference
```

For selective export choose another fresh output path and add `--person owner`,
`--project Cedar`, `--since 2026-10-01 --until 2026-10-06`, `--conversation-id UUID`
or `--task-id UUID`. Repeat `--section` or `--format` to select multiple values.
Project labels use project-memory key prefixes, exact knowledge namespaces and
task-goal prefixes. Project conversations follow matching memory provenance;
this is not a semantic project classifier. Date-only inputs cover UTC calendar
days; timestamps without a timezone are interpreted as UTC. Actions have no
recorded creation timestamp and are omitted from date-filtered exports.

5. Rebuild the restored derived index while ADAM is closed. This requires the
   installed E5 embedding assets, but no generation model. The previous index
   and receipt are quarantined rather than deleted. A running Qdrant owner
   causes an explicit `RESTORE.INDEX_BUSY` failure.

```powershell
& $pythonExe -m adam.resilience.cli --data-dir $restored rebuild-index
```

6. Run fault-injection QA. It creates disposable synthetic stores, damages only
   its own test index/database, tests recovery and exports readable sections.
   It verifies that every original recovery-store file remains byte-identical.
   This avoids damaging your personal store for the manual gate.

```powershell
& $pythonExe scripts\qa-wave7.py
.\scripts\check.ps1
```

With the configured compact Qwen server running on port 8080, reproduce the
real-model restore and E5 checks:

```powershell
& $pythonExe scripts\qa-wave7.py --real-model
```

The helper uses an ephemeral API port and downloads nothing. It does not stop
your model server. Reports are saved under `docs\operations\evidence`.

## Operating limits and recovery

Backup envelopes encrypt content, names and manifests with AES-256-GCM and a
separate Argon2id-derived key. An authenticated manifest includes schema versions,
identity digest, file sizes and SHA-256 checksums. Creation reserves writers,
copies committed SQLite state, verifies the encrypted archive from disk and only
then publishes it. A busy writer or integrity failure yields a visible failure.
Backups do not include models, vectors, traces, profile stores, exports or other
backups. They include owner state, identity, settings, canonical source blobs and
the tool sandbox. Default limits: 256 MiB payload and 10,000 archive members.

Keep defaults are daily 7, weekly 4, monthly 3 and milestone 10. Configure
`[backup]` with `keep_daily`, `keep_weekly`, `keep_monthly`, `keep_milestone`
(1–100) and `max_bytes` (1–256 MiB). Retention applies only to managed archives of
the newly created generation after its verification succeeds. Generations are
chosen explicitly; no unattended schedule is installed.

Vault content is excluded by default. `backup --include-vault` includes its
already sealed database; `restore --restore-vault` is separately required to
restore it. Its original vault passphrase or original Windows DPAPI account is
still required. A backup passphrase does not unlock that inner protection.

Restore stages and verifies into a new directory. It revokes tokens, leases and
pending approvals, pauses unfinished tasks and marks pending actions uncertain.
Historical receipts remain reported evidence rather than fresh verification.
Canonical source copies are rebound to the new directory; unrelated external
allowed roots are not retained. Restore does not execute tools or resume tasks.
Changing `ADAM_DATA_DIR` explicitly selects the restored installation; ensure an
unrelated `ADAM_CONFIG` is not overriding its saved settings.

Corrupt core data, schema drift or invalid identity/configuration discovered at
startup selects `RECOVERY_READ_ONLY` before migrations and consolidation. HTTP
serves safe health only and blocks private operations. Close ADAM after a storage
failure and use the local OS-trusted maintenance CLI to inspect/export/restore.
Recovery can run without a model:

```powershell
.\scripts\start.ps1 -Recovery
& $pythonExe -m adam.resilience.cli --data-dir $restored export 'C:\REPLACE\new-salvage-directory' --recovery
```

Recovery export labels unreadable sections `PARTIAL`; it never reports a complete
salvage of damaged data. An unresolved nonempty SQLite WAL requires stopping its
writers before immutable inspection. Do not delete a WAL or bypass that error.
Normal maintenance requires owner reauthentication; recovery CLI relies on access
to the local Windows account and does not initialize an authentication database.

Human exports are cleartext portability files, not restorable backups. Vault/auth,
working instructions, other profiles and full source bodies are excluded.
Recognized, declared and registered credentials are removed or block export;
arbitrary undeclared strings cannot be reliably classified as secrets. CSV cells
that could be formulas are escaped, while JSON retains original record values.
Unconfirmed candidates and uncertainty remain unconfirmed. The default record
limit is 10,000, maximum 100,000, with a 100,000-row scan limit and 32 MiB output
payload limit. Limits fail visibly instead of silently truncating output.

## Forgetting and purge scope

`/forget KEY_OR_ID` removes the matching memory family, including archived/history
records, derived summaries/candidates and identifiable supporting/echoed turns;
it clears related working/summary state. Future core snapshots reflect those
deletions. This is not a complete installation-wide purge: canonical knowledge
blobs, independent task/action journals, existing encrypted backup generations,
prior exports and external copies have separate lifecycles. Manage those copies
explicitly if you require their removal. Restoring an older backup can reintroduce
forgotten data. Neither logical deletion nor removing a file guarantees forensic
erasure from an SSD. Wave 7 does not automate destructive purge of older copies.

Record Gate 7 as passed only after reviewing the isolated restore and exported
data yourself. Wave 8 remains unstarted until you accept this wave.
