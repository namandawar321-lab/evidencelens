"""Count cached answers. Does not call the model."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "llm_cache"
RESULTS = Path(__file__).resolve().parent / "results_citations.csv"
FIELDS = ["clip_id", "question", "validated", "attempts", "abstained", "first_pass"]


def load_entries() -> list[dict]:
    rows = []
    if not CACHE.is_dir():
        return rows
    for path in sorted(CACHE.glob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        answer = entry.get("answer") if isinstance(entry.get("answer"), dict) else entry
        if not isinstance(answer, dict):
            continue
        validated = answer.get("_validated")
        if validated is None:
            validated = entry.get("validation_status")
        attempts = answer.get("_attempts")
        abstained = answer.get("abstained") is True
        first_pass = attempts == 1 and validated is True
        rows.append({
            "clip_id": entry.get("clip_id") or answer.get("_clip_id") or "",
            "question": entry.get("question") or "",
            "validated": validated is True,
            "attempts": attempts if attempts is not None else "",
            "abstained": abstained,
            "first_pass": first_pass,
        })
    return rows


def summarise(rows: list[dict]) -> dict:
    total = len(rows)
    return {
        "total": total,
        "validated": sum(1 for row in rows if row["validated"] is True),
        "retried": sum(1 for row in rows if isinstance(row["attempts"], int) and row["attempts"] > 1),
        "abstained": sum(1 for row in rows if row["abstained"] is True),
        "first_pass": sum(1 for row in rows if row["first_pass"] is True),
    }


def main() -> None:
    rows = load_entries()
    counts = summarise(rows)
    total = counts["total"]
    with RESULTS.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"cached answers {total}/{total}")
    print(f"validated {_pair(counts['validated'], total)}")
    print(f"more than one attempt {_pair(counts['retried'], total)}")
    print(f"abstained {_pair(counts['abstained'], total)}")
    print(f"first-pass validated {_pair(counts['first_pass'], total)}")


def _pair(count: int, total: int) -> str:
    return f"{count}/{total}"


if __name__ == "__main__":
    main()
