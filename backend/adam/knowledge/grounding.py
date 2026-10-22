"""Conservative extractive answers: retrieved text is evidence, never verified truth."""

import re
from typing import Literal, Protocol

from adam.core.contracts import Contract
from adam.knowledge.retrieval import (
    Evidence,
    QueryRequest,
    RetrievalResult,
    RetrievalService,
    terms,
)

STOP = set(
    (
        "a an the is are was were be been do does did how what when where which who why "
        "to of for in on at and or with my its it from can me tell about ka ki ke kis din "
        "hota hai ko aur kya use uses using"
    ).split()
)
ALIASES = {
    "backups": "backup",
    "files": "file",
    "documents": "document",
    "images": "image",
    "downloads": "download",
    "failed": "fail",
    "starts": "start",
    "launch": "start",
    "launching": "start",
    "scheduled": "schedule",
    "retries": "retry",
    "retrying": "retry",
    "logs": "log",
    "events": "event",
}
ATTRIBUTES = [
    {"salary", "wage", "wages", "payroll"},
    {"license", "licensing"},
    {"founder", "founded", "founds"},
    {"price", "cost", "costs", "pricing"},
    {"birthday", "born", "birth"},
    {"employees", "headcount"},
]


def meaningful(text: str) -> set[str]:
    return {ALIASES.get(term, term) for term in terms(text.replace("_", " ")) if term not in STOP}


class Reranker(Protocol):
    def rank(self, query: str, evidence: list[Evidence]) -> list[Evidence]: ...


class CoverageReranker:
    """Small CPU reranker; replaceable by a future cross-encoder without changing contracts."""

    def rank(self, query: str, evidence: list[Evidence]) -> list[Evidence]:
        query_terms = meaningful(query)
        ranked = []
        for item in evidence:
            coverage = len(query_terms & meaningful(item.chunk.text)) / max(1, len(query_terms))
            score = 0.55 * (item.semantic_score or 0) + 0.35 * coverage + 3 * item.rank_score
            ranked.append(item.model_copy(update={"rank_score": score}))
        return sorted(ranked, key=lambda item: (-item.rank_score, item.chunk.chunk_id))


class Sufficiency(Contract):
    sufficient: bool
    reason: str
    coverage: float
    semantic_peak: float
    semantic_margin: float


class Conflict(Contract):
    field: str
    alternatives: dict[str, list[str]]


class GroundedAnswer(Contract):
    status: Literal["EVIDENCE", "ABSTAIN", "CONFLICT"]
    text: str
    epistemic_status: Literal["RETRIEVED", "UNKNOWN"]
    citations: list[Evidence]
    sufficiency: Sufficiency
    conflicts: list[Conflict]
    retrieval: RetrievalResult
    policy: str = "extractive-v1; source quotations, no generated factual claims"


def assess(query: str, evidence: list[Evidence]) -> Sufficiency:
    query_terms = meaningful(query)
    union = set().union(*(meaningful(item.chunk.text) for item in evidence))
    coverage = len(query_terms & union) / max(1, len(query_terms))
    dense = sorted(
        [item.semantic_score for item in evidence if item.semantic_score is not None], reverse=True
    )
    peak = dense[0] if dense else 0
    margin = peak - dense[1] if len(dense) > 1 else peak
    missing_attribute = any(query_terms & group and not union & group for group in ATTRIBUTES)
    lexical = (
        bool(query_terms) and coverage >= 0.65 and any(item.keyword_score > 0 for item in evidence)
    )
    semantic = peak >= 0.83 and margin >= 0.025
    sufficient = bool(evidence) and not missing_attribute and (lexical or semantic)
    reason = (
        "requested_attribute_absent"
        if missing_attribute
        else "relevant_excerpts_found"
        if sufficient
        else "insufficient_relevance"
    )
    return Sufficiency(
        sufficient=sufficient,
        reason=reason,
        coverage=round(coverage, 3),
        semantic_peak=round(peak, 3),
        semantic_margin=round(margin, 3),
    )


def conflicts(evidence: list[Evidence]) -> list[Conflict]:
    claims: dict[str, dict[str, list[str]]] = {}
    for item in evidence:
        for line in item.chunk.text.splitlines():
            match = re.fullmatch(
                r"\s*([\w][\w ._-]{0,79}?)\s*(?:[:=]|\bis\b)\s*([^\n]{1,200})\s*", line
            )
            if match:
                key = " ".join(terms(match[1].replace("_", " ")))
                value = match[2].strip().rstrip(".").casefold()
                claims.setdefault(key, {}).setdefault(value, []).append(item.citation)
    return [
        Conflict(field=key, alternatives=values)
        for key, values in claims.items()
        if len(values) > 1
        and len({citation for citations in values.values() for citation in citations}) > 1
    ]


class GroundingService:
    def __init__(self, retrieval: RetrievalService, reranker: Reranker | None = None) -> None:
        self.retrieval = retrieval
        self.reranker = reranker or CoverageReranker()

    def answer(self, request: QueryRequest) -> GroundedAnswer:
        # Overfetch for reranking, then enforce the user's evidence limit.
        result = self.retrieval.search(request.model_copy(update={"limit": 10}))
        ranked = self.reranker.rank(request.query, result.evidence)
        sufficiency = assess(request.query, ranked)
        if not sufficiency.sufficient:
            return GroundedAnswer(
                status="ABSTAIN",
                text="I do not have sufficient current source evidence to answer that.",
                epistemic_status="UNKNOWN",
                citations=[],
                sufficiency=sufficiency,
                conflicts=[],
                retrieval=result,
            )
        query_terms = meaningful(request.query)
        peak = max((item.semantic_score or 0 for item in ranked), default=0)
        relevant = [
            item
            for item in ranked
            if (
                len(query_terms & meaningful(item.chunk.text)) / max(1, len(query_terms)) >= 0.35
                or (item.semantic_score or 0) >= max(0.83, peak - 0.035)
            )
        ]
        if not relevant:
            relevant = ranked[:1]
        potential_conflicts = conflicts(relevant)
        # Never hide a detected competing value merely because an excerpt limit is low.
        competing = {
            label
            for conflict in potential_conflicts
            for labels in conflict.alternatives.values()
            for label in labels
        }
        selected = [
            item
            for index, item in enumerate(relevant)
            if index < request.limit or item.citation in competing
        ]
        heading = (
            "Sources contain conflicting values; I cannot choose one as authoritative."
            if potential_conflicts
            else "Relevant source excerpts (their claims are not independently verified):"
        )
        excerpts = []
        for item in selected:
            # Quote every line: imported document instructions remain visibly quoted data.
            quote = "\n".join("> " + line for line in item.chunk.text.splitlines())
            excerpts.append(
                f"[{item.citation}]\n{quote}\nSource: {item.source.title} | {item.source.path} | "
                f"version {item.source.version} | {item.chunk.locator} | "
                f"source {item.source.source_id}"
            )
        if result.excluded_stale:
            heading += (
                f" {result.excluded_stale} changed/missing sources were excluded; "
                "reingest to update them."
            )
        # Canonical revision guard; API/runtime also guards the commit boundary.
        if result.revision != self.retrieval.revision():
            raise ValueError("Knowledge changed before answer; retry.")
        return GroundedAnswer(
            status="CONFLICT" if potential_conflicts else "EVIDENCE",
            text=heading + "\n\n" + "\n\n".join(excerpts),
            epistemic_status="RETRIEVED",
            citations=selected,
            sufficiency=sufficiency,
            conflicts=potential_conflicts,
            retrieval=result,
        )
