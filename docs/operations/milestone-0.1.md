# Milestone 0.1 checkpoint

2026-10-05. Foundation acceptance: 7 tests passed; Ruff lint and format passed;
strict mypy passed (9 source files). Isolated editable install verified on C:.

Config precedence, event/error round trips, explicit data path, invalid model URL,
unimplemented flags, empty database initialization, repeated migration, and failure
rollback tested. No personal-data schemas added. Startup command documented.

The F: volume does not record Git ownership and performs poorly with many small
files. Use command-scoped `git -c safe.directory="F:/Project Adam"`; do not change
global Git trust. Python environment lives under local application data on C:.
