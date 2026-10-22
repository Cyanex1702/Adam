# Wave 6 completion and QA - ADAM 0.6.0

Milestones 7.0-7.2 are implemented in the PC repository. Wave 6 is
AUTOMATED_VERIFIED; Gate 6 human validation remains pending. Wave 7 has not begun.

## Delivered

- Protected developer console with ordered timelines, configured model metadata,
  measured process RAM, latency stages and fixed subsystem failure classifications.
- Tool permission/result traces, task dependency graph data and memory/RAG metadata
  inspectors. Chat bodies, tool arguments, source bodies and hidden reasoning are omitted.
- Isolated scenario replay, release/model baselines and compatible-run score comparisons.
- Ten zero-tolerance security fixtures and common known-secret encoding protection,
  including partial tokens and whitespace-separated encodings.
- Reproducible `scripts/check.ps1` and `scripts/qa-wave6.py` checks.

## Verification on this PC

| Check | Result | Evidence |
|---|---|---|
| Regression tests | 114 passed | Final `scripts/check.ps1` run |
| Ruff lint and formatting | Passed, 130 Python files | Final check run |
| Strict mypy | Passed, 53 source files | Final check run |
| Framework + security suite | 22/22; zero critical failures | `evidence/wave6-full-eval.json` |
| Real Qwen/E5 evaluation | 12/12 | `evidence/wave6-real-model-eval.json` |
| Grounding regression | 19/19; zero unsupported emitted factual claims in fixtures | `evidence/wave6-grounding-eval.json` |
| E5 retrieval | 10/10; Recall@5 = 1.0 against 0.9 target; 20 documents | `evidence/wave6-retrieval-eval.json` |
| Live loopback API | 18/18 | `evidence/wave6-live-qa.json` |
| Browser checks | 8 passed observations | `evidence/wave6-browser-qa.json` |
| Earlier action/task live regression | 33/33 on 0.6.0 | `evidence/wave5-live-qa.json` |

Qwen ran on CPU with three threads and a 4,096-token context using the existing
Q4_K_M model. E5 used pinned installed local embedding assets. QA used temporary
synthetic stores and left personal owner data untouched. Only QA-owned services
were stopped afterward. No model downloads or GPU allocation were needed.

## Practical limits

Default scripted probes measure framework behavior, not model quality. Real Qwen
results use finite smoke rubrics. Extractive grounding and ranking remain heuristic;
these fixtures do not establish universal correctness. The attack cases cover
defined boundaries, not every encoding or prompt injection. Unknown arbitrary
secrets cannot be inferred by the privacy detector.

The console exposes configured model capabilities and checks health/alias; it does
not discover every backend capability. RAM measures the API process alone. GPU
VRAM is unavailable. Trace stages may overlap. A dependency emits a Starlette
TestClient deprecation warning; all checks pass.

No storage migration was added. The older SQLite migration helper now closes
connections on Windows without changing migration SQL or checksums. Wave 5's
explicit approval and sandbox scope remain enforced. See `gate-6.md` to validate
this wave in normal use.
