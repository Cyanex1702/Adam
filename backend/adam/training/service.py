import hashlib
import json
from typing import Any, Literal

from pydantic import Field

from adam.core.contracts import Contract, new_id
from adam.core.privacy import contains_secret
from adam.core.storage import ConversationStore
from adam.evals.suite import EvalReport, compare
from adam.memory.service import normalize
from adam.security.request import check_authority


class TrainingError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Example(Contract):
    id: str = Field(default_factory=new_id, pattern=r"^[a-f0-9-]{36}$")
    category: Literal["response_behavior", "tool_selection", "structured_output", "formatting"]
    prompt: str = Field(min_length=1, max_length=2000)
    response: str = Field(min_length=1, max_length=2000)
    approved: Literal[True]
    synthetic_behavior_only: Literal[True]
    permission_to_export: Literal[True]


class Training:
    def __init__(self, store: ConversationStore) -> None:
        self.store = store

    def enabled(self) -> bool:
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM training_settings WHERE key='enabled'").fetchone()
        return bool(row and row[0] == "true")

    def configure(self, enabled: bool) -> dict[str, Any]:
        with self.store.connect() as db:
            check_authority()
            db.execute(
                "INSERT INTO training_settings VALUES ('enabled',?) ON CONFLICT(key) "
                "DO UPDATE SET value=excluded.value",
                (json.dumps(enabled),),
            )
        return self.status()

    def required(self) -> None:
        if not self.enabled():
            raise TrainingError("TRAINING.EXPERIMENT_DISABLED")

    def status(self) -> dict[str, Any]:
        with self.store.connect() as db:
            count = db.execute("SELECT count(*) FROM training_examples").fetchone()[0]
        return {
            "enabled": self.enabled(),
            "approved_examples": count,
            "experiment": "DEFERRED_NO_VALIDATED_ADAPTER",
            "active_adapter": None,
            "automatic_conversation_collection": False,
            "note": "Manual synthetic behavior only. Training/promotion need separate evaluation.",
        }

    def add(self, value: Example) -> dict[str, str]:
        self.required()
        if not value.prompt.strip() or not value.response.strip():
            raise TrainingError("TRAINING.CONTENT_DENIED")
        self.content_guard(value)
        with self.store.connect() as db:
            check_authority()
            if db.execute("SELECT count(*) FROM training_examples").fetchone()[0] >= 1000:
                raise TrainingError("TRAINING.EXAMPLE_LIMIT")
            db.execute(
                "INSERT INTO training_examples VALUES (?,?) ON CONFLICT(id) "
                "DO UPDATE SET record=excluded.record",
                (value.id, value.model_dump_json()),
            )
        return {"id": value.id, "status": "APPROVED_SYNTHETIC_EXAMPLE"}

    def content_guard(self, value: Example) -> None:
        if contains_secret(value.model_dump_json()):
            raise TrainingError("TRAINING.CONTENT_DENIED")
        text = normalize(value.prompt + " " + value.response)
        with self.store.connect() as db:
            rows = db.execute("SELECT record FROM memories").fetchall()
        for row in rows:
            content = normalize(json.loads(row[0])["content"])
            if len(content) >= 8 and len(content.split()) >= 2 and content in text:
                raise TrainingError("TRAINING.PERSONAL_MEMORY_OVERLAP")

    def remove(self, identifier: str) -> None:
        with self.store.connect() as db:
            check_authority()
            db.execute("DELETE FROM training_examples WHERE id=?", (identifier,))

    def dataset(self) -> dict[str, Any]:
        self.required()
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT record FROM training_examples ORDER BY id LIMIT 1001"
            ).fetchall()
        if not rows or len(rows) > 1000:
            raise TrainingError("TRAINING.DATASET_SIZE")
        examples = [Example.model_validate_json(row[0]) for row in rows]
        for item in examples:
            self.content_guard(item)
        # The browser receives this exact reviewed payload; no filesystem path or network export.
        values = [
            {
                "id": item.id,
                "category": item.category,
                "messages": [
                    {"role": "user", "content": item.prompt},
                    {"role": "assistant", "content": item.response},
                ],
            }
            for item in examples
        ]
        encoded = "".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in values
        )
        return {
            "format": "adam.synthetic-behavior.v1",
            "examples": len(values),
            "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "jsonl": encoded,
            "attestation": "Owner attested synthetic behavior examples without personal facts.",
            "warning": "Secret filtering is heuristic. Review the full payload before export.",
        }


def assess(base: EvalReport, candidate: EvalReport, target: str) -> dict[str, Any]:
    comparison = compare(candidate, base)
    categories = {case.category for case in base.cases}
    cases_match = {(item.name, item.category, item.critical) for item in base.cases} == {
        (item.name, item.category, item.critical) for item in candidate.cases
    }
    real = base.execution.startswith("real-model") and candidate.execution == base.execution
    distinct = base.model.get("model_id") != candidate.model.get("model_id")
    complete = (
        base.suite == candidate.suite == "full-v1"
        and len(base.cases) == len(candidate.cases) >= 22
        and len({item.name for item in base.cases}) == len(base.cases)
        and len({item.name for item in candidate.cases}) == len(candidate.cases)
    )
    comparable = bool(comparison["comparable"] and cases_match and real and distinct and complete)
    no_regression = comparable and not any(
        old.passed and not next(item for item in candidate.cases if item.name == old.name).passed
        for old in base.cases
    )

    # Derive scores from case outcomes; uploaded summary scores cannot claim an improvement.
    def score(report: EvalReport, category: str) -> float:
        values = [item.passed for item in report.cases if item.category == category]
        return sum(values) / len(values) if values else 0.0

    delta = score(candidate, target) - score(base, target)
    eligible = (
        comparable
        and no_regression
        and candidate.critical_failures == 0
        and not any(item.critical and not item.passed for item in candidate.cases)
        and target in categories
        and delta > 0
    )
    return {
        "status": "HUMAN_REVIEW_REQUIRED" if eligible else "REJECTED_OR_DEFERRED",
        "comparable": comparable,
        "no_case_regression": bool(no_regression),
        "target": target,
        "target_delta": delta if comparable else None,
        "adapter_activated": False,
        "note": "Imported reports are owner-supplied evidence, not authenticated measurements. "
        "No automatic promotion; verify lineage, privacy and representative human conversations.",
    }
