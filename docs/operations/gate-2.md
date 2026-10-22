# Human Validation Gate 2 — Persistent ADAM

Wave 2 is AUTOMATED_VERIFIED. Gate 2 is NOT_STARTED. Wave 1 was accepted by the
user on 2026-10-05. Test this wave across sessions and preferably more than one day.

Start from PowerShell:

```powershell
Set-Location '%PROJECT_ROOT%'
.\scripts\start.ps1
```

If an older terminal is open, exit it with `/quit` and start again to load the new code.
Your selected Qwen 4B model is unchanged. No additional model download is needed.
SQLite memory uses ordinary local CPU/storage; it does not load another model.

1. Enter `/remember --pin preference editor = VS Code` and
   `/remember project current project = ADAM`. These are test facts: use facts you
   actually want stored, or forget them afterward. Explicit keys make corrections clear.
2. Enter `/show memory editor`. Check content, REPORTED status, confidence, source
   session/trace, UTC dates, audiences, privacy, and pin state. The operation is verified;
   your claim is reported evidence, not an independently verified fact.
3. Enter `/why know editor`. It should show the original owner statement provenance.
4. Enter `/sessions`, copy your session ID, and `/quit`. Restart with the same command.
   Enter `/resume YOUR_SESSION_ID`. Ask which editor you prefer, then inspect provenance.
   Start another conversation with `/new` and ask again: durable facts cross sessions.
5. Enter `/correct editor = Cursor`, then `/show memory --history editor`.
   Cursor should be CURRENT and VS Code HISTORICAL, with matching temporal boundaries.
6. Enter `/remember semantic operating system = I might switch to Linux`.
   `/show memory --history operating system` should show POSSIBLE/UNCERTAIN. It must
   not become a confirmed current statement that you use Linux.
7. Ask about a personal preference you never supplied. ADAM should abstain. The
   deterministic `/show memory UNMENTIONED_TOPIC` must return no matching memory.
8. Enter `/remember semantic test nickname = River`, then `That is wrong.`.
   It should retire and mark the focused statement disputed. Enter
   `/correct test nickname = Brook` to supply a replacement. Ambiguous references
   require an exact key or ID; ADAM must not invent the replacement.
9. Enter `/instruction Always answer in Roman Urdu` and `/task Finish the prototype`.
   Hold a longer conversation (more than eight turns). Use `/working` to inspect the
   rolling summary and last token budget. Check that your instruction and task survive
   summaries and a restart. Summaries are incomplete extracts; full history is separate.
10. Say `My preferred keyboard is mechanical`. Enter `/candidates` to inspect the
    suggestion. It is not durable memory yet. Use `/accept CANDIDATE_ID` to remember
    it or `/reject CANDIDATE_ID` to dismiss it. Ordinary greetings should create no
    durable memories or candidates. Supported candidate grammar is intentionally narrow.
11. Enter `/remember episodic test event = Tried a new keyboard`, then
    `/archive test event`. `/show memory test event` should omit it;
    `/show memory --archive test event` should find it. Pinned items require `/unpin KEY`
    before explicit archival and never expire automatically.
12. Run `/consolidate` twice. The second pass should report no redundant merges or
    summary changes when source facts are unchanged. Create two project facts to
    inspect a derived project summary; it should retain source IDs and restrictive privacy.
13. Enter `/forget test nickname`, then inspect it using both `--history` and `--archive`.
    It should be gone. Restart and query again. Forgetting removes all versions for the
    key and identifiable supporting/echoed turns and invalidates summaries. It does not
    promise forensic erasure of external backups, disk sectors, or unidentifiable paraphrases.
14. Forget any remaining synthetic test facts you do not want kept. Never test with
    real passwords, tokens, private keys, or other credentials.

Useful commands: `/pin KEY`, `/unpin KEY`, `/working`, `/status`, `/new`, `/sessions`,
`/resume ID`, `/quit`. Memory types: `semantic`, `episodic`, `preference`, `project`, `goal`.
Use `--private` after `/remember` for private owner memory. "Remember this: CONTENT"
and "Remember this permanently: CONTENT" also work; the latter pins the item.

API mode: `scripts\start.ps1 -Api`, then http://127.0.0.1:8765/docs. History is
paginated via `GET /sessions/{id}/history`; working state and budget are inspectable
via `GET /sessions/{id}/working`. A killed process's session lock expires within a
minute; clean exits release it immediately.

Gate passes when memory is coherent across restarts, corrections preserve history,
uncertain statements stay uncertain, provenance is inspectable, and forgetting and
archival behave as expected. Record acceptance or concrete failures before Wave 3.

Acceptance: 2026-10-05 — the user requested Wave 3, accepting the Wave 2 handoff. Individual manual checklist results were not separately reported.
