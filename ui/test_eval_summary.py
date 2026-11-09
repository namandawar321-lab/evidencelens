"""Temp-file checks for the eval footer counts. No app, no API.

    python ui/test_eval_summary.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.eval_summary import eval_counts, footer_text

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((PASS if condition else FAIL, name, detail))


def write_csv(folder: Path, name: str, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


VALIDATOR = """name,expected,actual,pass_fail,error
bad_one,reject,reject,pass,
bad_two,reject,accept,fail,
gap_one,gap,accept,pass,
good_one,accept,accept,pass,
good_two,accept,reject,fail,
"""
ABSTENTION = """clip_id,question,expected,decision,abstained
c,who,abstain,cannot_determine,True
c,steal,abstain,yes,False
c,zone,answer,yes,False
c,bag,answer,cannot_determine,True
"""
CITATIONS = """clip_id,question,validated,attempts,abstained,first_pass
c,one,True,1,False,True
c,two,True,2,False,False
c,three,False,1,True,False
"""
LAST = (
    "Event detection accuracy has not been measured on a labelled set. "
    "Every answer is for human review, not proof."
)


def test_normal(folder: Path) -> None:
    write_csv(folder, "results_validator.csv", VALIDATOR)
    write_csv(folder, "results_abstention.csv", ABSTENTION)
    write_csv(folder, "results_citations.csv", CITATIONS)
    counts = eval_counts(folder)
    validator = counts["validator"]
    abstention = counts["abstention"]
    citations = counts["citations"]
    check("normal validator caught", validator == {
        "caught": 1, "bad": 3, "wrongly_rejected": 1, "good": 2,
    }, str(validator))
    check("normal abstention", abstention == {
        "refused": 1, "unanswerable": 2, "answered": 1, "normal": 2,
    }, str(abstention))
    check("normal citations", citations == {
        "validated": 2, "total": 3, "first_pass": 1,
    }, str(citations))
    text = footer_text(folder)
    check(
        "normal footer",
        text == (
            "Checked on small test sets: the validator caught 1/3 bad replies and "
            "wrongly rejected 1/2 good ones; the system refused 1/2 unanswerable "
            "questions; 2/3 answers passed validation, 1 on the first attempt. "
            + LAST
        ),
        text,
    )


def test_missing(folder: Path) -> None:
    write_csv(folder, "results_citations.csv", CITATIONS)
    counts = eval_counts(folder)
    check("missing validator is none", counts["validator"] is None)
    check("missing abstention is none", counts["abstention"] is None)
    check("present citations still load", counts["citations"]["total"] == 3)
    text = footer_text(folder)
    check(
        "missing files drop their clauses",
        text.startswith("Checked on small test sets: 2/3 answers passed validation")
        and "validator" not in text
        and "unanswerable" not in text
        and text.endswith(LAST),
        text,
    )
    check("all missing shows only the last two sentences", footer_text(folder / "absent") == LAST)


def test_malformed(folder: Path) -> None:
    write_csv(folder, "results_validator.csv", "not,a,result\n1,2,3\n")
    write_csv(folder, "results_abstention.csv", "")
    write_csv(folder, "results_citations.csv", "validated\nTrue\n")
    counts = eval_counts(folder)
    check("malformed validator is none", counts["validator"] is None)
    check("empty abstention file is none", counts["abstention"] is None)
    check("citations missing first_pass is none", counts["citations"] is None)
    check("malformed set shows only the last two sentences", footer_text(folder) == LAST)


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test_normal(root / "normal")
        test_missing(root / "missing")
        test_malformed(root / "bad")
    failed = 0
    for status, name, detail in results:
        line = f"{status}: {name}"
        if detail and status == FAIL:
            line += f" — {detail}"
        print(line)
        if status == FAIL:
            failed += 1
    print(f"{len(results) - failed}/{len(results)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
