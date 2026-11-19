"""
JARVIS routing evaluation.

Checks that realistic requests take the right path (instant local answer, the right tool, or
plain conversation) using the deterministic intent classifier + planner. No AI model and no
network are used, so it is safe to run on every change and in CI.

    venv\\Scripts\\python.exe scripts\\run_eval.py            # table + pass rate
    venv\\Scripts\\python.exe scripts\\run_eval.py --json     # machine-readable
    venv\\Scripts\\python.exe scripts\\run_eval.py --min-pass 0.95
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CASES = ROOT / "tests" / "eval" / "routing_cases.json"


def route(request: str) -> dict:
    """What JARVIS would do with this request, without executing anything."""
    from core.brain.assistant_orchestrator import AssistantOrchestrator
    from core.brain.intent_classifier import IntentClassifier

    local = IntentClassifier().classify(request)
    # Only these built-ins short-circuit planning (see AssistantOrchestrator.process)
    if local and (local[0].startswith("_local") or local[0] == "_open_url_local"):
        return {"kind": "local", "local": local[0], "tools": []}
    orchestrator = AssistantOrchestrator(brain=None, tool_router=None, memory_manager=None, reasoning_engine=None)
    plan = orchestrator._create_plan(request, "chat")
    tools = [s.tool_name for s in plan if s.tool_name]
    return {"kind": "tools" if tools else "chat", "local": None, "tools": tools}


def check(case: dict, got: dict) -> bool:
    exp = case["expect"]
    if "local" in exp:
        return got["kind"] == "local" and got["local"] == exp["local"]
    if exp.get("chat"):
        return got["kind"] == "chat"
    if "tool" in exp:
        return got["kind"] == "tools" and got["tools"][0] == exp["tool"]
    if "tool_any" in exp:
        return got["kind"] == "tools" and got["tools"][0] in exp["tool_any"]
    if "chat_or_tool" in exp:
        return got["kind"] == "chat" or (got["kind"] == "tools" and got["tools"][0] in exp["chat_or_tool"])
    raise ValueError(f"unknown expectation in case {case['id']}")


def run_eval(cases_path: Path = CASES) -> dict:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        got = route(case["request"])
        results.append({"id": case["id"], "request": case["request"], "expect": case["expect"],
                        "got": got, "passed": check(case, got)})
    passed = sum(r["passed"] for r in results)
    return {"total": len(results), "passed": passed, "pass_rate": passed / max(1, len(results)), "results": results}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-pass", type=float, default=1.0)
    args = ap.parse_args()

    report = run_eval()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for r in report["results"]:
            got = r["got"]["local"] or (", ".join(r["got"]["tools"]) if r["got"]["tools"] else "chat")
            print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']:<22} -> {got:<40} | {r['request']}")
        print(f"\n{report['passed']}/{report['total']} passed ({report['pass_rate']:.0%})")
    return 0 if report["pass_rate"] >= args.min_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
