"""Reproducible small RAG baseline using the installed, pinned ONNX model."""

import argparse
import json
import tempfile
from pathlib import Path
from time import perf_counter

from adam.core.config import KnowledgeConfig, load_settings
from adam.core.storage import ConversationStore
from adam.knowledge.contracts import SourceRequest
from adam.knowledge.retrieval import QueryRequest, RetrievalService
from adam.knowledge.service import KnowledgeService

DOCUMENTS = {
    "backup": (
        "Orchid backups run every Friday at 18:00 UTC. Restore snapshots "
        "using the orchard-restore command."
    ),
    "launch": (
        "To launch the Cedar service, execute cedar serve --port 9123. "
        "Its health endpoint is /healthz."
    ),
    "retry": (
        "The Maple ingestion worker retries failed downloads three times with exponential backoff."
    ),
    "encryption": (
        "The Birch archive protects stored files using AES-256-GCM "
        "encryption. Encryption keys are held separately."
    ),
    "logs": (
        "The Willow runtime writes operational logs under data/audit. "
        "Logs retain event metadata without conversation text."
    ),
    "sync": (
        "The Aspen sync agent operates only on local-network peers. It "
        "never sends documents to a public cloud."
    ),
    "cache": (
        "The Juniper image cache evicts least recently used items when it exceeds 512 megabytes."
    ),
    "support": (
        "The Spruce help desk accepts requests at the internal portal. "
        "Support hours are Monday to Thursday, 09:00 to 17:00."
    ),
    "migration": (
        "The Elm application checks SQLite migration checksums on "
        "startup. It refuses modified applied migrations."
    ),
    "theme": "The Acacia interface defaults to a dark background with amber status indicators.",
    "sensor": (
        "The Hazel temperature sensor samples once every sixty seconds "
        "and reports Celsius readings."
    ),
    "packing": (
        "The Olive shipping team wraps glass bottles in recycled paper "
        "before placing them in cardboard boxes."
    ),
    "garden": (
        "The Magnolia garden receives water at sunrise. Soil moisture "
        "determines irrigation duration."
    ),
    "music": "The Rowan orchestra rehearses on Wednesday evenings in the north auditorium.",
    "recipe": "The Chestnut bread recipe uses rye flour, warm water, yeast and a pinch of salt.",
    "cycling": (
        "The Alder cycling route follows the river for twelve kilometers "
        "before returning through the park."
    ),
    "library": (
        "The Cypress library lends books for fourteen days. Renewals are "
        "available through its catalog."
    ),
    "museum": "The Hawthorn museum exhibits local ceramics and closes on Tuesdays.",
    "meeting": "The Beech planning meeting takes place at 10:30 each Monday in room seven.",
    "training": "The Poplar training course covers first aid and fire evacuation procedures.",
}
CASES = [
    ("backup", "When are Orchid backups scheduled?"),
    ("launch", "Which command starts Cedar and which port does it listen on?"),
    ("retry", "How does Maple recover from a failed download?"),
    ("encryption", "How does Birch keep saved documents confidential?"),
    ("logs", "Where does Willow record its operational events?"),
    ("sync", "Does Aspen upload my files to the internet?"),
    ("cache", "What happens when Juniper stores too many images?"),
    ("backup", "Orchid ka backup kis din hota hai?"),
    ("launch", "Cedar سروس کیسے شروع کریں اور کون سا پورٹ استعمال ہوتا ہے؟"),
    ("encryption", "Birch محفوظ فائلوں کی حفاظت کیسے کرتا ہے؟"),
]


def evaluate(directory: Path) -> dict[str, object]:
    config = load_settings().knowledge
    knowledge = KnowledgeService(
        ConversationStore(directory / "runtime.sqlite3"),
        KnowledgeConfig(allowed_roots=[directory], embedding_dir=config.embedding_dir),
    )
    ids = {}
    for name, text in DOCUMENTS.items():
        path = directory / (name + ".md")
        path.write_text(text, encoding="utf-8")
        ids[name] = knowledge.ingest(SourceRequest(path=str(path))).source_id
    retrieval = RetrievalService(knowledge)
    try:
        started = perf_counter()
        receipt = retrieval.reindex()
        indexing_seconds = perf_counter() - started
        cases = []
        for expected, query in CASES:
            started = perf_counter()
            result = retrieval.search(QueryRequest(query=query))
            passed = result.mode == "HYBRID" and any(
                item.source.source_id == ids[expected] for item in result.evidence
            )
            cases.append(
                {
                    "query": query,
                    "expected": expected,
                    "passed": passed,
                    "mode": result.mode,
                    "elapsed_ms": round((perf_counter() - started) * 1000, 1),
                    "ranking": [
                        {
                            "name": item.source.title,
                            "dense": item.semantic_score,
                            "keyword": item.keyword_score,
                        }
                        for item in result.evidence
                    ],
                }
            )
        recall = sum(bool(case["passed"]) for case in cases) / len(cases)
        return {
            "passed": recall >= 0.9,
            "target_recall_at_5": 0.9,
            "recall_at_5": recall,
            "documents": len(DOCUMENTS),
            "cases": cases,
            "index": receipt,
            "indexing_seconds": round(indexing_seconds, 2),
            "note": (
                "Small synthetic baseline; measures retrieval, not answer "
                "correctness or general language support."
            ),
        }
    finally:
        retrieval.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Wave 3 real embedding RAG evaluation")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="adam-rag-eval-") as directory:
        report = evaluate(Path(directory))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
    print(json.dumps(report, ensure_ascii=True, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
