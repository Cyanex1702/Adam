import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from adam.core.config import load_settings
from adam.core.privacy import contains_secret
from adam.core.runtime import ChatRequest, Runtime
from adam.evals.scenarios import SCENARIOS
from adam.evals.suite import EvalReport, compare, evaluate, execute, names


async def run_scenarios(runtime: Runtime) -> dict[str, object]:
    results: list[dict[str, object]] = []
    for scenario in SCENARIOS:
        event = await runtime.chat(ChatRequest(text=scenario.prompt))
        answer = str(event.payload.get("text", ""))
        passed = event.event_type == "agent.completed" and scenario.passes(answer)
        results.append(
            {
                "name": scenario.name,
                "passed": passed,
                "event_type": event.event_type,
                "trace_id": event.trace_id,
            }
        )
        if not passed:
            results[-1]["error_code"] = "EVAL.RUBRIC_FAILED"
        if event.session_id:
            runtime.sessions.close(event.session_id)
    return {
        "passed": all(item["passed"] for item in results),
        "scenarios": results,
        "identity_digest": runtime.identity.digest,
        "model": runtime.provider.get_capabilities().model_dump(),
        "note": "Substring smoke rubrics; human judgment is still required.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ADAM isolated local evaluation and replay")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--real-model", action="store_true")
    parser.add_argument("--real-rag", action="store_true")
    parser.add_argument("--replay")
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--suite", choices=["local", "security", "full"], default="local")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    from adam.evals.security import ATTACKS, evaluate_security, execute_security

    if args.replay and args.replay not in [*names(), *ATTACKS]:
        parser.error("EVAL.UNKNOWN_SCENARIO")
    if args.replay:
        result = (
            asyncio.run(execute_security(args.replay, settings))
            if args.replay in ATTACKS
            else asyncio.run(
                execute(args.replay, settings, real_model=args.real_model, real_rag=args.real_rag)
            )
        )
        report = result.model_dump(mode="json")
    else:
        result_report = (
            asyncio.run(evaluate_security(settings))
            if args.suite == "security"
            else asyncio.run(evaluate(settings, real_model=args.real_model, real_rag=args.real_rag))
        )
        if args.suite == "full":
            security = asyncio.run(evaluate_security(settings))
            result_report.suite = "full-v1"
            result_report.dataset_digest = hashlib.sha256(
                (result_report.dataset_digest + security.dataset_digest).encode()
            ).hexdigest()
            result_report.cases.extend(security.cases)
            result_report.scores.update(security.scores)
            result_report.critical_failures += security.critical_failures
            result_report.passed = result_report.passed and security.passed
        report = result_report.model_dump(mode="json")
        if args.compare:
            raw = args.compare.read_text(encoding="utf-8")
            if len(raw) > 1048576 or contains_secret(raw):
                parser.error("Comparison report is oversized or contains credential material")
            report["comparison"] = compare(result_report, EvalReport.model_validate_json(raw))
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if contains_secret(encoded):
        parser.error("Report contains credential material; refusing output")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    if args.baseline_dir and not args.replay:
        model_key = hashlib.sha256(
            json.dumps(
                [report["model"], report["suite"], report["execution"]], sort_keys=True
            ).encode()
        ).hexdigest()[:16]
        baseline = args.baseline_dir / str(report["release"]) / f"{model_key}.json"
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(encoded, encoding="utf-8")
    # Windows pipes may use cp1252; the saved report is UTF-8, stdout stays portable ASCII.
    printed = (
        {
            "passed": report["passed"],
            "suite": report.get("suite", "replay"),
            "cases": len(report.get("cases", [])),
            "critical_failures": report.get("critical_failures", 0),
        }
        if args.summary
        else report
    )
    print(json.dumps(printed, ensure_ascii=True, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
