"""Checks for the validate() hardening. Does not call the model.

Two stress-test gaps are not asserted here: a verified negative has no field
that names its rule apart from the COV- id, and the reply shape does not
forbid extra fields.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ask import validate


def load_stress():
    path = Path(__file__).resolve().parent / "validator_stress.py"
    spec = importlib.util.spec_from_file_location("validator_stress", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EVIDENCE = {
    "events": [{
        "event_id": "EV-0001",
        "type": "zone_intrusion",
        "t_start": 3.68,
        "t_end": 5.44,
        "status": "confirmed_by_rule",
    }],
    "tracks": [],
}


def yes_reply(start, end):
    return {
        "decision": "yes",
        "abstained": False,
        "reason": "positive_evidence",
        "human_review_required": True,
        "claims": [{
            "text": "A person entered the zone.",
            "cited_ids": ["EV-0001"],
            "cited_time_range": [start, end],
        }],
    }


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"{mark}: {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        raise SystemExit(1)


def main() -> None:
    for value in (None, ["not", "a", "dict"], "not a dict"):
        ok, problems = validate(value, EVIDENCE)
        check(
            f"non-dict {type(value).__name__} is rejected",
            ok is False and problems == ["reply must be a JSON object"],
            str(problems),
        )

    mismatched = {
        "decision": "cannot_determine",
        "abstained": False,
        "reason": "insufficient_evidence",
        "claims": [],
        "human_review_required": True,
    }
    ok, problems = validate(mismatched, EVIDENCE)
    check(
        "cannot_determine with abstained false is rejected",
        ok is False and "cannot_determine requires abstained true" in problems,
        str(problems),
    )

    abstained_yes = {
        "decision": "yes",
        "abstained": True,
        "reason": "insufficient_evidence",
        "claims": [],
        "human_review_required": True,
    }
    ok, problems = validate(abstained_yes, EVIDENCE)
    check(
        "abstained true with decision yes is rejected",
        ok is False and "abstained true requires decision cannot_determine" in problems,
        str(problems),
    )

    clean = {
        "decision": "cannot_determine",
        "abstained": True,
        "reason": "insufficient_evidence",
        "claims": [],
        "human_review_required": True,
    }
    ok, problems = validate(clean, EVIDENCE)
    check("cannot_determine with abstained true still passes", ok, str(problems))

    ok, problems = validate(yes_reply(5.0, 4.0), EVIDENCE)
    check(
        "start after end is rejected",
        ok is False and any("is after end" in item for item in problems),
        str(problems),
    )
    ok, problems = validate(yes_reply(4, 5), EVIDENCE)
    check("integer endpoints still pass", ok, str(problems))
    ok, problems = validate(yes_reply(4.0, 4.0), EVIDENCE)
    check("equal start and end still passes", ok, str(problems))

    ok, problems = validate(yes_reply("3.68", "5.44"), EVIDENCE)
    check(
        "string endpoints are rejected",
        ok is False and any("must be numbers" in item for item in problems),
        str(problems),
    )

    stress = load_stress()
    packs = {key: stress.load_evidence(clip_id) for key, clip_id in stress.CLIPS.items()}
    good = [case for case in stress.build_cases(packs) if case["kind"] == "good"]
    check("six good replies are present", len(good) == 6, str(len(good)))
    for case in good:
        ok, problems = validate(case["answer"], case["evidence"])
        check(f"good reply still accepted: {case['name']}", ok, str(problems))

    print("PASS: validate hardening checks")


if __name__ == "__main__":
    main()
