# Evaluation methodology

The Python suite covers contracts, migrations, policy, memory/RAG, actions,
revocation, recovery and subsystem failure paths using disposable profiles.
Resource admission unit fixtures are explicitly synthetic. Live/frozen/installed
QA runs outside those fixtures and retains real resource guards.

`python -m adam.evals.runner --suite full --summary --output report.json` runs
22 finite synthetic framework/security scenarios. Without `--real-model`, its
transport is a scripted probe. `--real-model` and `--real-rag` select the configured
local assets; reports retain model metadata, execution mode and dataset digest.
Real-model runs use isolated test data rather than replaying owner conversations.

The portfolio dashboard bundles a freshly generated report and derives pass rates
from case outcomes. It labels scripted transport and scenario-duration scope.
No placeholder VRAM, voice metric or model-quality score is substituted for a
missing measurement. New personal/training/portfolio behaviors also have dedicated
failure-path and cross-profile tests; the 22-case benchmark is not exhaustive.

Windows QA exercises the actual frozen service/native host, controlled Win32
fixtures, update/rollback/restore and source-bundle relocation. A successful
automated run does not mark human gates as passed. Clean Windows/VM, alternate
physical hardware, human voice/social interaction and Android acceptance must
be recorded separately.

Fine-tuned candidates must be compared against base using matching full real-model
fixtures and representative human conversations. Per-case regressions, critical
failures, identity drift, privacy problems or absent target benefit block promotion.
Training loss and scripted-probe results cannot demonstrate adapter improvement.
