# Milestone 5.2 — Dry run, undo and journal

Verified on real temporary files on this PC: create/move/quarantine, inverse previews,
empty-directory undo, modified-file conflicts, snapshots and restart receipts.
Mutation intent is committed before filesystem work. Interrupted operations become
UNCERTAIN and require inspection; they are never automatically repeated. File
publication uses no-overwrite primitives. Quarantine retains content, and moves
keep a separate byte-verified snapshot. Undo requires a new approval and refuses
changed content or an occupied destination. No permanent recursive deletion exists.
Desktop actions use fixed Notepad or scoped text/Markdown/PDF dispatch; their result
is DISPATCHED with UNCERTAIN observation, never a fabricated success claim.
