# Gate 5 — Action and Task ADAM

Active source: `%PROJECT_ROOT%`. Start with:

```powershell
Set-Location -LiteralPath '%PROJECT_ROOT%'
.\scripts\start.ps1
```

Commands below go into ADAM's `You:` prompt, not PowerShell. The `/tools` command
prints the actual sandbox path. All tests use only that sandbox. Set an owner
passphrase with `/auth-init` if not already configured. Existing authentication
continues to work; use the passphrase you previously chose.

## File action walkthrough

1. Enter `/tools` and confirm its scope is a local `tool-sandbox` directory.
2. Enter `/tool {"name":"notes.create","arguments":{"path":"gate5.txt","text":"Gate five synthetic note"}}`.
   This returns PREVIEW, action_id, digest and preconditions. No file exists yet.
3. Enter `/deny-action ACTION_ID DIGEST`. Confirm `/actions` shows DENIED and
   `gate5.txt` does not exist. Create a new preview by repeating step 2.
4. Enter `/approve-action ACTION_ID DIGEST`, then `/run-action ACTION_ID`.
   Both use a hidden owner passphrase prompt. Confirm VERIFIED and actual file text.
5. Enter `/tool {"name":"files.read","arguments":{"path":"gate5.txt"}}` and
   `/tool {"name":"files.search","arguments":{"query":"gate5"}}`.
6. Preview a rename with `/tool {"name":"files.move","arguments":{"source":"gate5.txt","destination":"renamed.txt"}}`.
   Approve/run its ID and digest; verify the old name is absent and new name exists.
7. Enter `/undo MOVE_ACTION_ID`. This produces a NEW preview. Approve/run it to
   restore `gate5.txt`. Edit a file after previewing a move and confirm execution
   returns TOOL.STALE_PREVIEW without overwriting either file.
8. Preview `/tool {"name":"files.quarantine","arguments":{"path":"gate5.txt"}}`.
   Approve/run, then undo through a new approved preview. Content is retained in
   `.adam-quarantine`; byte-verified snapshots are kept in `.adam-snapshots`.

Do not reuse IDs from this guide; substitute the actual UUID and digest printed
by ADAM. Approved previews expire after five minutes. Mutations never run directly
from a `/tool` request or ordinary chat. Destination overwrites are refused.

## Task walkthrough

Create two small test notes with the approved procedure above, then:

1. `/plan diagnose .` produces a read-only search plan.
2. `/plan organize .` produces folder creation and individual file move steps
   grouped by extension. Review every step before approving.
3. `/approve-task TASK_ID DIGEST`, then `/run-task TASK_ID`. Confirm COMPLETED,
   every step's action receipt, and actual files in the extension folders.
4. `/tasks` and `/actions` show durable checkpoints. Quit and restart ADAM;
   rerunning the completed task returns its receipt without repeating moves.
5. Make another plan and `/cancel-task TASK_ID` before running. Confirm CANCELLED
   and no effects. Cancellation during execution stops between steps; it does not
   undo completed effects. Each move can be undone through its own action preview.
6. `/plan clean everything` must return TASK.CLARIFICATION_REQUIRED.
7. Start API mode with `scripts\start.ps1 -Api` in PowerShell, then use the
   authenticated API docs at `http://127.0.0.1:8765/docs` for structured
   `/tasks` plans and `/tasks/{id}/replan`. A fix_and_test plan requires a dependent
   read-only final step with expected_text. A failed verification cannot complete.

## Boundary and desktop checks

- `/tool {"name":"notes.create","arguments":{"path":"../outside.txt","text":"blocked"}}`
  must return TOOL.SCOPE_DENIED. Reserved Windows names, alternate data streams,
  reparse points, hard-linked files and private journal directories are denied.
- `/mode guest`, then try creating a note or planning organize: OWNER_REQUIRED.
  `/actions` and `/tasks` show only the separate profile's records. Returning to
  owner requires the hidden passphrase. Demo also uses a separate scope.
- Optional: preview `/tool {"name":"apps.open","arguments":{"application":"notepad"}}`.
  Approve/run to launch Notepad. The result is DISPATCHED, with UNCERTAIN window
  observation. Only Notepad is registered for application launch. Opening scoped
  `.txt`, `.md` and `.pdf` uses `files.open`; scripts/executables are denied.
- No unrestricted shell, browser automation, arbitrary application arguments or
  permanent recursive deletion is available.

## Automated checks and limitations

Run `scripts\check.ps1` for regression/static checks. Run the development Python
interpreter with `scripts\qa-wave5.py` for real loopback API and terminal QA.
The QA uses synthetic temporary PC data, launches only its own API process, and
requires no inference model. It never changes your normal authentication or notes.
Desktop dispatch is mocked in automated tests; manually observing its window is
the human check above.

Interrupted filesystem mutations are marked UNCERTAIN and require reviewing the
action record and actual files. They are never automatically replayed. Completed
receipts recover automatically. Retries are limited to read-only failures; replan
is limited to two replacements, requires a new approval, and rejects uncertain
effects. Task execution is explicit and serial; no background scheduler is enabled.
Windows file associations and another process running as your OS account remain
outside ADAM's application-level boundary. Snapshots/journals are local, cleartext
ordinary data; registered secrets are blocked, not stored there.

Report any incorrect file effect, approval bypass, false completion or previous
wave regression. Gate 5 remains pending your test; Wave 6 has not begun.
