"""Ask the abstention sheet through the same cache the app uses.

A cache hit does not call the model. An api_error or quota error stops the
run. That row is not saved. Rows already saved can be skipped on the next run.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_cache import ask_cached

QUESTIONS = Path(__file__).resolve().parent / "abstention_questions.csv"
RESULTS = Path(__file__).resolve().parent / "results_abstention.csv"
EVIDENCE_ROOT = ROOT / "data" / "evidence"
FIELDS = [
    "clip_id",
    "question",
    "category",
    "expected",
    "decision",
    "abstained",
    "validated",
    "attempts",
    "headline",
    "reason",
    "reply_text",
    "source",
    "correct",
]


def redact(text: str) -> str:
    key = os.environ.get("GEMINI_API_KEY") or ""
    if key and key in text:
        return text.replace(key, "[redacted]")
    return text


def load_questions() -> list[dict]:
    with QUESTIONS.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def format_time(seconds) -> str:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "00:00.0"
    sign = "-" if value < 0 else ""
    value = abs(value)
    minutes = int(value // 60)
    remain = value - minutes * 60
    return f"{sign}{minutes:02d}:{remain:04.1f}"


def cited_event(evidence: dict, answer: dict) -> dict | None:
    for claim in answer.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for cid in claim.get("cited_ids") or []:
            if str(cid).startswith("EV-"):
                found = next(
                    (item for item in evidence.get("events") or [] if item.get("event_id") == str(cid)),
                    None,
                )
                if found:
                    return found
    events = evidence.get("events") or []
    return events[0] if events else None


def user_headline(answer: dict, evidence: dict, question: str) -> str:
    """The simple-view sentence. Same words as the Investigate page."""
    if answer.get("status") == "api_error":
        return "Could not reach the language model. Try again."
    decision = answer.get("decision")
    if answer.get("abstained") or decision in (None, "cannot_determine"):
        return "Can't tell from this clip."
    if decision == "yes":
        event = cited_event(evidence, answer)
        verbs = {
            "zone_intrusion": "entered the restricted area",
            "unattended_object": "left a bag behind",
        }
        if not event:
            return "Something was recorded in this clip."
        verb = verbs.get(str(event.get("type")), "was recorded")
        return (
            f"Someone {verb} between {format_time(event.get('t_start'))} "
            f"and {format_time(event.get('t_end'))}."
        )
    if decision == "no":
        text = question.lower()
        if "fall" in text:
            return "No fall found."
        if any(word in text for word in ("unattended", "bag", "suitcase", "object", "left")):
            return "No left-behind bag found."
        return "No entry found."
    return "Can't tell from this clip."


def is_yes_no(row: dict) -> bool:
    return str(row.get("decision")) in {"yes", "no"}


def score_rows(rows: list[dict]) -> dict:
    """Score saved rows. Does not call the model."""
    abstain_rows = [row for row in rows if row.get("expected") == "abstain"]
    controls = [row for row in rows if row.get("expected") == "answer"]
    correct = [
        row for row in abstain_rows
        if row.get("abstained") is True and not is_yes_no(row)
    ]
    failures = [row for row in abstain_rows if is_yes_no(row)]
    over = [row for row in controls if row.get("abstained") is True]
    return {
        "abstain_correct": len(correct),
        "abstain_total": len(abstain_rows),
        "failures": failures,
        "over_abstention": len(over),
        "control_total": len(controls),
        "over_rows": over,
    }


def row_result(question: dict, result: dict) -> dict:
    answer = result.get("answer") or {}
    evidence = json.loads(
        (EVIDENCE_ROOT / question["clip_id"] / "evidence.json").read_text(encoding="utf-8")
    )
    abstained = answer.get("abstained") is True
    record = {
        "clip_id": question["clip_id"],
        "question": question["question"],
        "category": question["category"],
        "expected": question["expected"],
        "decision": "" if answer.get("decision") is None else answer.get("decision"),
        "abstained": abstained,
        "validated": answer.get("_validated"),
        "attempts": answer.get("_attempts"),
        "headline": user_headline(answer, evidence, question["question"]),
        "reason": "" if answer.get("reason") is None else answer.get("reason"),
        "reply_text": redact(json.dumps(answer, ensure_ascii=False)),
        "source": result.get("source") or "",
        "correct": "",
    }
    if question["expected"] == "abstain":
        record["correct"] = "yes" if abstained and not is_yes_no(record) else "no"
    else:
        record["correct"] = "no" if abstained else "yes"
    return record


def is_stop(answer: dict, detail: str = "") -> bool:
    """Stop only when this call failed. A saved answer can mention an earlier 429."""
    if answer.get("status") == "api_error":
        return True
    text = f"{detail}".lower()
    return any(word in text for word in ("quota", "resource exhausted", "rate limit", "429"))


def load_saved() -> list[dict]:
    if not RESULTS.is_file():
        return []
    with RESULTS.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["abstained"] = str(row.get("abstained")).lower() == "true"
    return rows


def write_rows(rows: list[dict]) -> None:
    with RESULTS.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in FIELDS})


def print_score(rows: list[dict]) -> None:
    scored = score_rows(rows)
    print(f"abstain correct {scored['abstain_correct']}/{scored['abstain_total']}")
    print("yes/no on an abstain question:")
    if scored["failures"]:
        for row in scored["failures"]:
            print(f"- {row.get('question')} ({row.get('decision')})")
    else:
        print("- none")
    print(f"over-abstention {scored['over_abstention']}/{scored['control_total']}")
    for row in scored["over_rows"]:
        print(f"- {row.get('clip_id')}: {row.get('question')}")


def main() -> None:
    questions = load_questions()
    saved = load_saved()
    done = {(row["clip_id"], row["question"]) for row in saved}
    pending = [row for row in questions if (row["clip_id"], row["question"]) not in done]
    for index, question in enumerate(pending):
        try:
            result = ask_cached(question["clip_id"], question["question"])
        except BaseException as exc:
            detail = redact(str(exc))
            remaining = len(pending) - index
            print(f"stopped: {detail}")
            print(f"{remaining}/{len(questions)} rows remain")
            print_score(saved)
            return
        answer = result.get("answer") or {}
        if is_stop(answer):
            remaining = len(pending) - index
            print("stopped: api_error or quota. This row was not saved.")
            print(f"{remaining}/{len(questions)} rows remain")
            print_score(saved)
            return
        saved.append(row_result(question, result))
        write_rows(saved)
    print_score(saved)
    print(f"rows saved {len(saved)}/{len(questions)}")


if __name__ == "__main__":
    main()
