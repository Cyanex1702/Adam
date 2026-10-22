# Milestone 4.0

Principal and resource policies are evaluated outside the model. Audience, profile, disclosure owner, subjects, authenticated identity, trusted-device state and sensitivity have deterministic denial codes. Secrets/unknown sensitivity fail closed. Memory selection and knowledge snapshot/embedding filtering use the same engine before content matching or model context. Existing owner records default to the owner profile and their policy hash format is preserved.

60 tests, Ruff and strict mypy pass, including constructed-model-input exclusion and legacy duplicate-source identity. Guest/demo entry points and authentication arrive in 4.1.
