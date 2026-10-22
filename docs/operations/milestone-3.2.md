# Milestone 3.2

Automated verified: replaceable CPU coverage reranker, lexical/semantic sufficiency,
extractive answer policy, repeated-field conflicts, accurate source attribution and
developer retrieval inspector. Explicit `/ask`/knowledge_namespace routes operate
without the generation model and preserve RETRIEVED evidence separately from memory.

56 tests and static checks pass. Real answer evaluation: 19/19. Live API: 25 assertions;
terminal: 8 checks; prior Qwen smoke: 7/7. See wave-3-report.md and evidence JSON.

Extractive answers are the deliberate Wave 3 implementation choice: they avoid
unsupported model-generated factual synthesis and reduce resource use. RETRIEVED
does not assert source truth. General contradiction detection and free-form supported
synthesis remain limitations; Gate 3 must assess usefulness on the user's own documents.
