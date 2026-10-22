# Behavior training — Wave 19 (experimental)

The experiment is off by default. No trained adapter is bundled or activated.
ADAM works with the base model throughout. Actual training and human comparison
remain **DEFERRED** pending an approved use case, a reviewed dataset and supported
GPU hardware. Training loss alone cannot qualify an adapter.

Open **Behavior experiment**, reauthenticate as owner, and enable it explicitly.
Approve synthetic behavior examples one at a time: response behavior, tool choice,
formatting or structured output. Each requires explicit approval, a synthetic-only
attestation and permission to export. Conversations are never collected automatically.
Recognized credentials and verbatim known personal memory overlap are rejected.
These checks cannot identify every personal fact: manually review every example.

Review the complete JSONL and its SHA-256 before copying it to a separate training
environment. Examples can be deleted through `POST /training/remove {"id":"UUID"}`.
Disabling the experiment blocks dataset/recipe access. Restore retains approved
examples but resets enablement, requiring renewed local consent.

The downloadable/copyable Python recipe supports LoRA and QLoRA in a separate
Colab/Kaggle CUDA environment. It requires 20–1000 distinct approved prompts, a
pinned model revision, a matching dataset hash, a fresh output folder and a
supported CUDA GPU. It masks user tokens, uses a holdout split, records dependency
versions and saves an adapter separately. This recipe has been syntax checked;
no GPU training run is claimed. It does not upload data or alter ADAM's active model.

The implementation follows the [official PEFT quantization guide](https://huggingface.co/docs/peft/en/developer_guides/quantization)
and [Transformers Trainer guidance](https://huggingface.co/docs/transformers/en/trainer).

Evaluate base and adapter through the same full ADAM real-model regression suite.
Paste both reports and a target category into **Compare base and candidate**.
The assessor requires matching fixtures, execution mode and case sets; distinct
model identifiers; no per-case regression; no critical failure; and measured target
improvement. It derives scores from cases rather than trusting report aggregates.
Scripted probes do not qualify. Owner-supplied reports are not authenticated
measurements. A qualifying report requests human review; nothing automatically
promotes or loads an adapter. Keep using the base model unless a separate model
validation and human gate approves a candidate.
