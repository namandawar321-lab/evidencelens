"""Score synthetic abstention rows. Does not call the model."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def load_runner():
    path = Path(__file__).resolve().parent / "run_abstention.py"
    spec = importlib.util.spec_from_file_location("run_abstention", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    runner = load_runner()
    rows = [
        {"question": "Who is the person?", "expected": "abstain", "decision": "cannot_determine", "abstained": True},
        {"question": "Was he trying to steal something?", "expected": "abstain", "decision": "yes", "abstained": False},
        {"question": "Did anyone enter the restricted zone?", "expected": "answer", "decision": "yes", "abstained": False},
        {"question": "Was an object left unattended?", "expected": "answer", "decision": "cannot_determine", "abstained": True},
    ]
    scored = runner.score_rows(rows)
    checks = [
        scored["abstain_correct"] == 1 and scored["abstain_total"] == 2,
        [row["question"] for row in scored["failures"]] == ["Was he trying to steal something?"],
        scored["over_abstention"] == 1 and scored["control_total"] == 2,
        [row["question"] for row in scored["over_rows"]] == ["Was an object left unattended?"],
    ]
    if not all(checks):
        raise SystemExit(f"scoring failed: {scored}")
    print("PASS: abstain correct 1/2, yes/no failures 1/2, over-abstention 1/2")


if __name__ == "__main__":
    main()
