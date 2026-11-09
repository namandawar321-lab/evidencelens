"""Stress-test the real validate() on purpose-built replies.

Does not call the model. Does not change the validator.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ask import validate

EVIDENCE_ROOT = ROOT / "data" / "evidence"
RESULTS = Path(__file__).resolve().parent / "results_validator.csv"

# cav_walk2: no events, zone_intrusion negative_eligible true, coverage present.
# live_20261030_120041: the loaded clips have no needs_review event; this one does.
CLIPS = {
    "cav_walk1": "cav_walk1",
    "bagleftreal": "bagleftreal",
    "live": "live_20261030_131248",
    "no_events": "cav_walk2",
    "needs_review": "live_20261030_120041",
}


def load_evidence(clip_id: str) -> dict:
    path = EVIDENCE_ROOT / clip_id / "evidence.json"
    return json.loads(path.read_text(encoding="utf-8"))


def first_event(evidence: dict) -> dict:
    return (evidence.get("events") or [])[0]


def claim(text: str, cited_ids, start=None, end=None) -> dict:
    item = {"text": text, "cited_ids": cited_ids}
    if start is not None:
        item["cited_time_range"] = [start, end]
    return item


def reply(decision: str, abstained: bool, reason: str, claims, **extra) -> dict:
    body = {
        "decision": decision,
        "abstained": abstained,
        "reason": reason,
        "claims": claims,
        "human_review_required": True,
    }
    body.update(extra)
    return body


def build_cases(packs: dict[str, dict]) -> list[dict]:
    walk = packs["cav_walk1"]
    bag = packs["bagleftreal"]
    live = packs["live"]
    empty = packs["no_events"]
    review = packs["needs_review"]
    walk_ev = first_event(walk)
    bag_ev = first_event(bag)
    live_ev = first_event(live)
    review_ev = first_event(review)
    cases = []

    def add(name: str, evidence: dict, answer, expected: str, why: str, kind: str, gap: str = "") -> None:
        cases.append({
            "name": name,
            "kind": kind,
            "evidence": evidence,
            "answer": answer,
            "expected": expected,
            "why": why,
            "gap": gap,
        })

    add(
        "unknown_event_id",
        walk,
        reply("yes", False, "positive_evidence", [
            claim("A person entered.", ["EV-9999"], walk_ev["t_start"], walk_ev["t_end"]),
        ]),
        "reject",
        "Cites EV-9999, which is not in cav_walk1.",
        "bad",
    )
    add(
        "unknown_track_id",
        walk,
        reply("yes", False, "positive_evidence", [
            claim("A person was present.", ["TRK-9999"], 2.16, 6.72),
        ]),
        "reject",
        "Cites TRK-9999, which is not in cav_walk1.",
        "bad",
    )
    add(
        "time_outside_half_second",
        walk,
        reply("yes", False, "positive_evidence", [
            claim("A person entered.", [walk_ev["event_id"]], 0.0, 1.0),
        ]),
        "reject",
        "Cited 0.0-1.0 is more than 0.5 s outside EV-0001 (3.68-5.44).",
        "bad",
    )
    add(
        "yes_without_confirmed_event",
        walk,
        reply("yes", False, "positive_evidence", [
            claim("A person was present.", ["TRK-2"], 2.16, 6.72),
        ]),
        "reject",
        "Yes cites only TRK-2, not a confirmed_by_rule event.",
        "bad",
    )
    add(
        "yes_cites_unconfirmed_event",
        review,
        reply("yes", False, "positive_evidence", [
            claim("A bag was left.", [review_ev["event_id"]], review_ev["t_start"], review_ev["t_end"]),
        ]),
        "reject",
        "live_20261030_120041 EV-0001 is needs_review, not confirmed_by_rule.",
        "bad",
    )
    add(
        "no_without_cov",
        empty,
        reply("no", False, "verified_negative", [
            claim("The zone rule found no entry.", ["TRK-4"], 4.24, 7.2),
        ]),
        "reject",
        "A no cites TRK-4 and no COV- id.",
        "bad",
    )
    add(
        "no_when_not_eligible",
        walk,
        reply("no", False, "verified_negative", [
            claim("The bag rule found nothing.", ["COV-unattended_object"], 0.0, 24.76),
        ]),
        "reject",
        "cav_walk1 unattended_object negative_eligible is false.",
        "bad",
    )
    add(
        "no_wrong_rule_cov",
        live,
        reply("no", False, "verified_negative", [
            claim("The zone rule found no entry.", ["COV-unattended_object"], 0.0, 26.079),
        ]),
        "reject",
        "The claim is about a zone entry but cites COV-unattended_object.",
        "bad",
        "validate() checks that the cited COV rule is eligible and has no overlapping event. It does not check that the cited rule is the one the sentence is about, so this bag-rule no is accepted.",
    )
    add(
        "no_while_event_exists",
        walk,
        reply("no", False, "verified_negative", [
            claim("The zone rule found no entry.", ["COV-zone_intrusion"], 0.0, 24.76),
        ]),
        "reject",
        "Full-clip no for zone_intrusion overlaps cav_walk1 EV-0001.",
        "bad",
    )
    add(
        "abstain_with_claims",
        walk,
        reply("cannot_determine", True, "insufficient_evidence", [
            claim("A person entered.", [walk_ev["event_id"]], walk_ev["t_start"], walk_ev["t_end"]),
        ]),
        "reject",
        "abstained is true but claims is not empty.",
        "bad",
    )
    add(
        "cannot_determine_but_not_abstained",
        walk,
        reply("cannot_determine", False, "insufficient_evidence", [
            claim("A person entered.", [walk_ev["event_id"]], walk_ev["t_start"], walk_ev["t_end"]),
        ]),
        "reject",
        "decision is cannot_determine but abstained is false.",
        "bad",
        "validate() allows cannot_determine with abstained false when the claim itself is well formed.",
    )
    add(
        "bad_decision_value",
        walk,
        reply("maybe", False, "positive_evidence", [
            claim("A person entered.", [walk_ev["event_id"]], walk_ev["t_start"], walk_ev["t_end"]),
        ]),
        "reject",
        "decision 'maybe' is not yes, no, or cannot_determine.",
        "bad",
    )
    missing = {
        "decision": "yes",
        "abstained": False,
    }
    add(
        "missing_required_fields",
        walk,
        missing,
        "reject",
        "reason, claims, and human_review_required are absent.",
        "bad",
    )
    add(
        "claims_or_cited_ids_wrong_type",
        walk,
        reply("yes", False, "positive_evidence", (
            {"text": "A person entered.", "cited_ids": "EV-0001", "cited_time_range": [3.68, 5.44]},
        )),
        "reject",
        "claims is a tuple, not a list, and cited_ids is a string.",
        "bad",
    )
    add(
        "yes_empty_claims",
        walk,
        reply("yes", False, "positive_evidence", []),
        "reject",
        "A yes answer has an empty claims list.",
        "bad",
    )
    add(
        "time_start_after_end",
        walk,
        reply("yes", False, "positive_evidence", [
            claim("A person entered.", [walk_ev["event_id"]], 5.0, 4.0),
        ]),
        "reject",
        "cited_time_range is 5.0 then 4.0, both inside the event span.",
        "bad",
        "validate() checks that each endpoint lies in the span. It does not require the start to be before the end.",
    )
    add(
        "time_range_as_strings",
        walk,
        reply("yes", False, "positive_evidence", [
            claim("A person entered.", [walk_ev["event_id"]], "3.68", "5.44"),
        ]),
        "reject",
        "cited_time_range values are strings, not numbers.",
        "bad",
        "validate() calls float() on the endpoints, so numeric strings are accepted.",
    )
    add(
        "extra_unknown_field",
        walk,
        reply(
            "yes", False, "positive_evidence",
            [claim("A person entered.", [walk_ev["event_id"]], walk_ev["t_start"], walk_ev["t_end"])],
            confidence_score=0.99,
        ),
        "gap",
        "The reply schema does not forbid extra fields, and validate() does not check them.",
        "bad",
        "The prompt's JSON shape does not forbid extra fields, and validate() never checks for them.",
    )
    add(
        "yes_event_from_other_clip",
        empty,
        reply("yes", False, "positive_evidence", [
            claim("A bag was left.", [bag_ev["event_id"]], bag_ev["t_start"], bag_ev["t_end"]),
        ]),
        "reject",
        "Cites bagleftreal EV-0001 while the evidence is cav_walk2, which has no events.",
        "bad",
    )
    add(
        "reply_not_an_object",
        walk,
        None,
        "reject",
        "The reply is None, not a JSON object.",
        "bad",
        "validate() assumes a dict and raises TypeError on None instead of returning a rejection.",
    )

    add(
        "good_yes_zone",
        walk,
        reply("yes", False, "positive_evidence", [
            claim("A person entered the zone.", [walk_ev["event_id"]], walk_ev["t_start"], walk_ev["t_end"]),
        ]),
        "accept",
        "cav_walk1 EV-0001 is confirmed_by_rule and the times are copied.",
        "good",
    )
    add(
        "good_yes_bag",
        bag,
        reply("yes", False, "positive_evidence", [
            claim("A bag was left.", [bag_ev["event_id"]], bag_ev["t_start"], bag_ev["t_end"]),
        ]),
        "accept",
        "bagleftreal EV-0001 is confirmed_by_rule and the times are copied.",
        "good",
    )
    add(
        "good_no_zone",
        empty,
        reply("no", False, "verified_negative", [
            claim("The zone rule found no zone intrusion over the full clip.", ["COV-zone_intrusion"], 0.0, 42.52),
        ]),
        "accept",
        "cav_walk2 has no zone event and zone_intrusion is negative_eligible.",
        "good",
    )
    add(
        "good_abstain",
        walk,
        reply("cannot_determine", True, "insufficient_evidence", []),
        "accept",
        "Abstention with an empty claims list.",
        "good",
    )
    add(
        "good_no_window_before_event",
        live,
        reply("no", False, "verified_negative", [
            claim("The zone rule found no zone intrusion between 0 s and 10 s.", ["COV-zone_intrusion"], 0.0, 10.0),
        ]),
        "accept",
        "The live clip's zone event starts at 16.216 s, after this window.",
        "good",
    )
    add(
        "good_yes_inside_tolerance",
        walk,
        reply("yes", False, "positive_evidence", [
            claim(
                "A person entered the zone.",
                [walk_ev["event_id"]],
                float(walk_ev["t_start"]) - 0.4,
                float(walk_ev["t_end"]) + 0.4,
            ),
        ]),
        "accept",
        "The cited range is inside the 0.5 s tolerance of EV-0001.",
        "good",
    )
    return cases


def run_case(case: dict) -> tuple[str, str]:
    try:
        ok, problems = validate(case["answer"], case["evidence"])
    except Exception as exc:
        return "error", f"{type(exc).__name__}: {exc}"
    message = "; ".join(str(item) for item in problems)
    return ("accept" if ok else "reject"), message


def judge(expected: str, actual: str) -> str:
    if expected == "gap":
        return "pass" if actual == "accept" else "fail"
    if expected == actual:
        return "pass"
    return "fail"


def main() -> list[dict]:
    packs = {key: load_evidence(clip_id) for key, clip_id in CLIPS.items()}
    cases = build_cases(packs)
    rows = []
    for case in cases:
        actual, message = run_case(case)
        rows.append({
            "name": case["name"],
            "kind": case["kind"],
            "expected": case["expected"],
            "actual": actual,
            "pass_fail": judge(case["expected"], actual),
            "error": message,
            "why": case["why"],
            "gap": case["gap"],
        })
    with RESULTS.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["name", "expected", "actual", "pass_fail", "error"],
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in writer.fieldnames})

    print(f"{'name':<36} {'expected':<8} {'actual':<8} {'pass':<6} error")
    for row in rows:
        shown = row["error"].replace("\n", " ")
        if len(shown) > 110:
            shown = shown[:107] + "..."
        print(f"{row['name']:<36} {row['expected']:<8} {row['actual']:<8} {row['pass_fail']:<6} {shown}")

    bad = [row for row in rows if row["kind"] == "bad"]
    good = [row for row in rows if row["kind"] == "good"]
    caught = sum(1 for row in bad if row["actual"] == "reject")
    false_reject = sum(1 for row in good if row["actual"] == "reject")
    print()
    print(f"bad replies caught {caught}/{len(bad)}")
    print(f"good replies wrongly rejected {false_reject}/{len(good)}")
    print("gaps:")
    for row in bad:
        if row["actual"] == "reject":
            continue
        detail = row["gap"] or row["why"]
        print(f"- {row['name']}: {detail}")
    return rows


if __name__ == "__main__":
    main()
