# Milestone 3.0

Automated verified: schema 6 adds versioned sources, paths, original blob hashes and chunks. UTF-8 text, Markdown, common code and extractable PDF pages are parsed without code execution. Same content and policy in one namespace deduplicate; renamed paths regain canonical identity when ingested. Changed/deleted paths are excluded until explicit reingestion. Original blobs and prior revisions remain canonical. Credential-bearing files and disallowed roots are rejected.

49 tests, Ruff and strict mypy passed. No OCR or automatic filesystem watcher.
