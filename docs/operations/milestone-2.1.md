# Milestone 2.1 — Working memory

AUTOMATED_VERIFIED, 2026-10-05. 31 tests plus Ruff and strict mypy passed.

Schema 3 stores objective, entities, task state, explicit instructions, and last context
budget. /instruction TEXT and /task TEXT set terminal working fields. API GET/PUT
/sessions/{id}/working inspect/replace state. The prefix "For this conversation"
also retains an explicit instruction separately from the rolling summary.

Summaries use bounded extracts labelled owner-reported/assistant-unverified with turn
references. They retain original uncertainty wording, cap at 2048 characters, and advance
incrementally in the same successful-turn transaction. Recent-turn count is configurable.
The full transcript is separate. Summary is intentionally lossy, not a durable fact store.

ContextBuilder uses the provider tokenizer with conservative fallback, reserves output,
prunes oldest recent turns then summary/retrieval blocks, and never truncates the current
input or explicit instruction/task block. Oversized protected context fails explicitly.
Started/completed events and stored session state expose token budget and dropped turns.
A stale-result pruning interface exists without enabling tools.

Tests exercise 40 archived turns, restart, possibility wording, bounded recent context,
pressure pruning, critical instruction preservation, and stale-result filtering.
