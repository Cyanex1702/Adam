# Contributing

Read [LICENSE](LICENSE), especially its contribution terms, before submitting a change.
Contributions are accepted under the Community Non-Commercial License v1.0; submission
grants Cyanex the rights described in Section 7. Third-party licenses remain separate.

Use a local Python 3.13 environment and install `requirements.lock.txt`, then
`python -m pip install -e .`. Run `python -m pytest -q`, `python -m ruff check backend tests`,
and `python -m mypy backend/adam`. Desktop development also requires Node and Rust:
`npm ci`, `npm test`, `npm run build` under `apps/desktop`; `cargo test` and
`cargo clippy -- -D warnings` under `apps/desktop/src-tauri`.

Keep model artifacts, runtimes, runtime data, credentials, generated installers and
personal evaluations out of Git. Use fictional data in tests and issue reports.
New persistent schemas require a migration and backup/restore coverage. New actions
must declare risk, scope and approval behavior. Add a meaningful failure-path test.

Describe the concrete problem, resulting behavior, validation and known limits in
your pull request. Do not mark pending human gates as passed using automated tests.
