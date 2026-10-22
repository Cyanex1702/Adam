# ADR 0003: identity and epistemic boundaries

Four versioned YAML files define identity, personality, communication, and epistemics.
They are bundled as package data and survive wheel installation/model replacement.
Explicit user identity directories override the bundle; incomplete or unsupported packs
fail startup. A SHA-256 pack digest identifies the exact configuration used in responses.
Model templates remain in the adapter. The pack contains no model-specific syntax.

GET `/identity` returns deterministic live capability availability and model metadata.
The same trusted state is injected into every turn. Conversation answers are marked
UNCERTAIN/model_generation, never VERIFIED merely because the model produced them.
No evidence retrieval is implemented. The seven epistemic statuses are available to
future evidence-producing services without pretending retrieval exists now.

Golden smoke scenarios run the actual configured model through Runtime. Rubrics are
simple substring checks, not comprehensive hallucination detectors. Prompt rules reduce
fake embodiment and invented personal facts but cannot mathematically guarantee arbitrary
model behavior. Human validation and future adversarial suites remain necessary.
