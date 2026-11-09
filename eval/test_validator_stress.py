"""Run the validator stress script and require every good reply to be accepted.

Bad replies that the validator misses are reported by validator_stress.py.
This file does not require those to be caught.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def load_stress():
    path = Path(__file__).resolve().parent / "validator_stress.py"
    spec = importlib.util.spec_from_file_location("validator_stress", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    stress = load_stress()
    rows = stress.main()
    good = [row for row in rows if row["kind"] == "good"]
    missed = [row["name"] for row in good if row["actual"] != "accept"]
    if missed:
        raise SystemExit(f"good replies were not all accepted: {missed}")
    results = Path(__file__).resolve().parent / "results_validator.csv"
    if not results.is_file():
        raise SystemExit("results_validator.csv was not written")
    print(f"PASS: script ran, {len(good)}/{len(good)} good replies accepted")


if __name__ == "__main__":
    main()
