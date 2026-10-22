import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from adam import APP_VERSION
from adam.core.contracts import Contract
from adam.core.privacy import contains_secret
from adam.evals.suite import EvalReport
from adam.resilience.archive import scoped
from adam.security.request import check_authority


class DemoTool(Contract):
    action: Literal["inspect", "write_note", "undo_note"]
    text: str = Field(default="Fictional Cedar demonstration note.", max_length=1000)


class PortfolioError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def benchmarks(path: Path | None = None) -> dict[str, Any]:
    source = path or Path(__file__).parent / "benchmark.json"
    if not source.is_file():
        return {"status": "UNAVAILABLE", "release": APP_VERSION, "measurements": None}
    if source.stat().st_size > 1048576:
        raise PortfolioError("PORTFOLIO.INVALID_REPORT")
    raw = source.read_text(encoding="utf-8")
    if contains_secret(raw):
        raise PortfolioError("PORTFOLIO.INVALID_REPORT")
    try:
        report = EvalReport.model_validate_json(raw)
    except ValueError:
        raise PortfolioError("PORTFOLIO.INVALID_REPORT") from None
    if not report.cases or any(
        not math.isfinite(item.duration_ms) or item.duration_ms < 0 for item in report.cases
    ):
        raise PortfolioError("PORTFOLIO.INVALID_REPORT")
    counts: dict[str, dict[str, Any]] = {}
    for case in report.cases:
        entry = counts.setdefault(case.category, {"passed": 0, "total": 0})
        entry["total"] += 1
        entry["passed"] += int(case.passed)
    for value in counts.values():
        value["rate"] = value["passed"] / value["total"]
    return {
        "status": "MEASURED",
        "release": report.release,
        "suite": report.suite,
        "execution": report.execution,
        "model": report.model,
        "dataset_digest": report.dataset_digest,
        "report_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "categories": counts,
        "critical_failures": report.critical_failures,
        "cases": [
            {
                "name": item.name,
                "category": item.category,
                "passed": item.passed,
                "duration_ms": item.duration_ms,
            }
            for item in report.cases
        ],
        "latency_scope": "Isolated scenario duration, including fixture setup; not token latency.",
        "vram_bytes": None,
        "voice_metrics": None,
        "unavailable": ["GPU VRAM telemetry", "voice benchmark measurements"],
        "note": report.note,
        "owner_data": "No owner traces, conversations or files are loaded.",
    }


def demo_tool(root: Path, value: DemoTool) -> dict[str, Any]:
    if contains_secret(value.text):
        raise PortfolioError("PORTFOLIO.CONTENT_DENIED")
    root = scoped(root, "portfolio-sandbox")
    root.mkdir(parents=True, exist_ok=True)
    note, undo = scoped(root, "fictional-note.txt"), scoped(root, "undo.json")
    for path in [note, undo]:
        if path.exists() and (
            path.stat().st_size > 65536 or contains_secret(path.read_text(encoding="utf-8"))
        ):
            raise PortfolioError("PORTFOLIO.CONTENT_DENIED")
    declaration = {"risk": "LOW", "scope": "this fictional demo profile only", "tool": value.action}
    check_authority()
    if value.action == "inspect":
        return {
            **declaration,
            "files": ["fictional-note.txt"] if note.exists() else [],
            "text": note.read_text(encoding="utf-8") if note.exists() else "No demo note created.",
        }
    if value.action == "write_note":
        if undo.exists():
            raise PortfolioError("PORTFOLIO.UNDO_PENDING")
        old = note.read_text(encoding="utf-8") if note.exists() else None
        undo.write_text(
            json.dumps(
                {"previous": old, "sha256": hashlib.sha256(value.text.encode()).hexdigest()}
            ),
            encoding="utf-8",
        )
        check_authority()
        note.write_text(value.text, encoding="utf-8")
        return {**declaration, "status": "VERIFIED", "text": note.read_text(encoding="utf-8")}
    if not undo.exists() or not note.exists():
        raise PortfolioError("PORTFOLIO.NO_UNDO")
    receipt = json.loads(undo.read_bytes())
    if hashlib.sha256(note.read_bytes()).hexdigest() != receipt["sha256"]:
        raise PortfolioError("PORTFOLIO.CHANGED_SINCE_WRITE")
    if receipt["previous"] is None:
        note.unlink()
    else:
        note.write_text(receipt["previous"], encoding="utf-8")
    undo.unlink()
    return {**declaration, "status": "UNDONE"}
