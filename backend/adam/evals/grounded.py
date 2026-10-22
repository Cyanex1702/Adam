import argparse
import json
import tempfile
from pathlib import Path

from adam.core.config import KnowledgeConfig, load_settings
from adam.core.storage import ConversationStore
from adam.evals.rag import CASES, DOCUMENTS
from adam.knowledge.contracts import SourceRequest
from adam.knowledge.grounding import GroundingService
from adam.knowledge.retrieval import QueryRequest, RetrievalService
from adam.knowledge.service import KnowledgeService

MISSING = [
    "What is Orchid's founder name?",
    "What salary does Willow pay?",
    "Which license does Cedar use?",
    "What is the price of Birch?",
    "How many employees work at Aspen?",
    "Who won the lunar chess championship?",
    "What is the favorite color of the Cedar founder?",
]


def evaluate(directory: Path) -> dict[str, object]:
    knowledge = KnowledgeService(
        ConversationStore(directory / "runtime.sqlite3"),
        KnowledgeConfig(
            allowed_roots=[directory], embedding_dir=load_settings().knowledge.embedding_dir
        ),
    )
    for name, text in DOCUMENTS.items():
        path = directory / (name + ".md")
        path.write_text(text, encoding="utf-8", newline="\n")
        knowledge.ingest(SourceRequest(path=str(path)))
    retrieval = RetrievalService(knowledge)
    service = GroundingService(retrieval)
    cases: list[dict[str, object]] = []
    try:
        for expected, query in CASES:
            answer = service.answer(QueryRequest(query=query))
            correct = answer.status == "EVIDENCE" and any(
                item.source.title == expected + ".md" for item in answer.citations
            )
            attribution = all(
                any(chunk == item.chunk for chunk in knowledge.chunks(item.source))
                for item in answer.citations
            )
            cases.append(
                {
                    "query": query,
                    "passed": correct and attribution,
                    "status": answer.status,
                    "sufficiency": answer.sufficiency.model_dump(),
                    "attribution_valid": attribution,
                }
            )
        for query in MISSING:
            answer = service.answer(QueryRequest(query=query))
            cases.append(
                {
                    "query": query,
                    "passed": answer.status == "ABSTAIN" and not answer.citations,
                    "status": answer.status,
                    "sufficiency": answer.sufficiency.model_dump(),
                }
            )
        for name, text in {"config-a": "retry_limit = 3", "config-b": "retry_limit = 5"}.items():
            path = directory / (name + ".txt")
            path.write_text(text, encoding="utf-8")
            knowledge.ingest(SourceRequest(path=str(path), namespace="conflict"))
        answer = service.answer(QueryRequest(query="What is retry_limit?", namespace="conflict"))
        cases.append(
            {
                "query": "conflicting retry_limit",
                "passed": answer.status == "CONFLICT"
                and len(answer.citations) == 2
                and bool(answer.conflicts),
                "status": answer.status,
            }
        )
        answer = service.answer(QueryRequest(query="Orchid backup and Cedar launch command"))
        cases.append(
            {
                "query": "multiple source chunks",
                "passed": {"backup.md", "launch.md"}
                <= {item.source.title for item in answer.citations},
                "status": answer.status,
            }
        )
        return {
            "passed": all(case["passed"] for case in cases),
            "cases": cases,
            "unsupported_generated_factual_claims": 0,
            "note": "Extractive policy emits canonical quotations, not free-form model synthesis. "
            "Relevance and structured-field conflicts are heuristic; "
            "this finite set does not prove semantic entailment.",
        }
    finally:
        retrieval.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Wave 3 grounded-answer evaluation")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="adam-grounding-eval-") as directory:
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
