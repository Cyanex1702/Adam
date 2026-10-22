# ADR 0001: foundation boundaries

Accepted 2026-10-05 for the user-authorized first implementation.

Python package `backend/adam` in a monorepo. FastAPI/CLI depend on core contracts;
core has no UI or framework orchestration dependency. Model adapters own wire formats.
Desktop package is explicitly inert until its milestone. Future modules are not created.

Configuration precedence: defaults, explicit TOML, process environment. `.env.example`
documents process variables and is not auto-loaded. Default data path is OS application
data; explicit paths override it. Experimental and unimplemented flags reject activation.

Schema migration 1 creates only metadata and migration bookkeeping. Migrations run in
one SQLite transaction, record checksums, reject future schemas, and are repeatable.
Personal conversation persistence is deferred to Wave 2.
