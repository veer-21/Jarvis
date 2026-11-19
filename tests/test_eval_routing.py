"""Routing evaluation gate: every realistic request must take the expected path (no AI calls)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_eval():
    spec = importlib.util.spec_from_file_location("run_eval", ROOT / "scripts" / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_routing_eval_passes():
    report = _load_eval().run_eval()
    failures = [f"{r['id']}: {r['request']!r} -> {r['got']}" for r in report["results"] if not r["passed"]]
    assert not failures, "Routing regressions:\n" + "\n".join(failures)
    assert report["total"] >= 30
