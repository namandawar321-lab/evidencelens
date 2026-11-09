"""Read measured eval counts for the footer. Missing or unreadable files are None."""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval"

_LAST = (
    "Event detection accuracy has not been measured on a labelled set. "
    "Every answer is for human review, not proof."
)


def eval_counts(directory: Path | None = None) -> dict:
    """Counts from the three result files. A missing or unreadable file is None."""
    folder = EVAL_DIR if directory is None else Path(directory)
    return {
        "validator": _validator(folder / "results_validator.csv"),
        "abstention": _abstention(folder / "results_abstention.csv"),
        "citations": _citations(folder / "results_citations.csv"),
    }


def footer_text(directory: Path | None = None) -> str:
    """The measured footer. A missing file drops its clause."""
    counts = eval_counts(directory)
    parts: list[str] = []
    validator = counts["validator"]
    if validator is not None:
        parts.append(
            f"the validator caught {validator['caught']}/{validator['bad']} bad replies "
            f"and wrongly rejected {validator['wrongly_rejected']}/{validator['good']} good ones"
        )
    abstention = counts["abstention"]
    if abstention is not None:
        parts.append(
            f"the system refused {abstention['refused']}/{abstention['unanswerable']} "
            "unanswerable questions"
        )
    citations = counts["citations"]
    if citations is not None:
        parts.append(
            f"{citations['validated']}/{citations['total']} answers passed validation, "
            f"{citations['first_pass']} on the first attempt"
        )
    if not parts:
        return _LAST
    return "Checked on small test sets: " + "; ".join(parts) + ". " + _LAST


def _rows(path: Path) -> tuple[list[str], list[dict]] | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    try:
        reader = csv.DictReader(text.splitlines())
        fields = [str(name).strip() for name in (reader.fieldnames or []) if name]
        if not fields:
            return None
        rows = []
        for row in reader:
            if not isinstance(row, dict):
                return None
            rows.append(row)
        return fields, rows
    except csv.Error:
        return None


def _validator(path: Path) -> dict | None:
    loaded = _rows(path)
    if loaded is None:
        return None
    fields, rows = loaded
    if not {"expected", "actual"} <= set(fields):
        return None
    caught = bad = wrongly = good = 0
    for row in rows:
        expected = str(row.get("expected") or "").strip().lower()
        actual = str(row.get("actual") or "").strip().lower()
        if not expected:
            continue
        if expected == "accept":
            good += 1
            if actual == "reject":
                wrongly += 1
        else:
            bad += 1
            if actual == "reject":
                caught += 1
    return {
        "caught": caught,
        "bad": bad,
        "wrongly_rejected": wrongly,
        "good": good,
    }


def _abstention(path: Path) -> dict | None:
    loaded = _rows(path)
    if loaded is None:
        return None
    fields, rows = loaded
    if not {"expected", "abstained", "decision"} <= set(fields):
        return None
    refused = unanswerable = answered = normal = 0
    for row in rows:
        expected = str(row.get("expected") or "").strip().lower()
        decision = str(row.get("decision") or "").strip().lower()
        if expected == "abstain":
            unanswerable += 1
            if _truth(row.get("abstained")) and decision not in {"yes", "no"}:
                refused += 1
        elif expected == "answer":
            normal += 1
            if not _truth(row.get("abstained")) and decision in {"yes", "no"}:
                answered += 1
    return {
        "refused": refused,
        "unanswerable": unanswerable,
        "answered": answered,
        "normal": normal,
    }


def _citations(path: Path) -> dict | None:
    loaded = _rows(path)
    if loaded is None:
        return None
    fields, rows = loaded
    if not {"validated", "first_pass"} <= set(fields):
        return None
    total = validated = first_pass = 0
    for row in rows:
        if not any(str(value or "").strip() for value in row.values()):
            continue
        total += 1
        if _truth(row.get("validated")):
            validated += 1
        if _truth(row.get("first_pass")):
            first_pass += 1
    return {"validated": validated, "total": total, "first_pass": first_pass}


def _truth(value) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}
