"""Synthetic tests for the EvidenceLens POC rules and citation validator.

No video, no GPU, no API key needed - the tracks are fabricated, so you can
check the rule logic before you have footage:

    python test_rules.py

Each scenario below is one row of the planned test set (requirements Section 7).
"""

from __future__ import annotations

import json
import sys

from build_evidence import (
    BAG_CLASSES, PERSON_CLASS, THRESHOLDS, Detection, Track,
    class_votes, majority_label, visible_tracks,
    rule_zone_intrusion, rule_unattended_object,
)
from ask import classify_api_error, validate

FPS = 10.0
PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((PASS if condition else FAIL, name, detail))


def make_track(tid: int, cls: int, label: str, samples) -> Track:
    """samples = [(t_s, (x1, y1, x2, y2)), ...]"""
    track = Track(tid, cls, label)
    for t_s, bbox in samples:
        track.dets.append(Detection(
            frame_idx=int(round(t_s * FPS)), t_s=round(t_s, 3), track_id=tid,
            cls=cls, label=label, conf=0.9, bbox=bbox,
        ))
    return track


def walk(t0, t1, x0, x1, y=400, w=60, h=160, step=0.1):
    """A person box sliding from x0 to x1 between t0 and t1 (y = foot line)."""
    out, n = [], max(1, int(round((t1 - t0) / step)))
    for i in range(n + 1):
        t = t0 + i * step
        x = x0 + (x1 - x0) * (i / n)
        out.append((t, (x - w / 2, y - h, x + w / 2, y)))
    return out


def still(t0, t1, cx, cy, w, h, step=0.1):
    out, n = [], max(1, int(round((t1 - t0) / step)))
    for i in range(n + 1):
        t = t0 + i * step
        out.append((t, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)))
    return out


ZONE = {"zone_id": "Z1", "camera_id": "test_cam", "label": "restricted door",
        "polygon": [[300, 300], [600, 300], [600, 500], [300, 500]], "version": 1}

# ---------------------------------------------------------------- intrusion

# 1. person walks through the zone and dwells 5 s -> one event
p = make_track(1, PERSON_CLASS, "person",
               walk(0, 2, 100, 350, y=400) + walk(2.1, 7, 400, 450, y=400)
               + walk(7.1, 9, 500, 800, y=400))
events = rule_zone_intrusion({1: p}, ZONE)
check("intrusion: dwell inside fires one event", len(events) == 1,
      f"got {len(events)}")
if events:
    ev = events[0]
    check("intrusion: dwell >= 1.0 s", ev["t_end"] - ev["t_start"] >= 1.0,
          f"{ev['t_start']}-{ev['t_end']}s")
    check("intrusion: rule_trace names the zone and the track",
          "Z1" in ev["rule_trace"] and "TRK-1" in ev["rule_trace"])

# 2. hard negative: walks along the border, foot point never inside -> no event
p2 = make_track(2, PERSON_CLASS, "person", walk(0, 9, 100, 290, y=400))
check("intrusion: border walk fires nothing",
      len(rule_zone_intrusion({2: p2}, ZONE)) == 0)

# 3. fast crossing of the zone, under the 1.0 s dwell -> no event
#    (0.5 s to cross the full 300 px width, so ~0.3 s of foot point inside)
p3 = make_track(3, PERSON_CLASS, "person",
                walk(0, 0.5, 250, 700, y=400, step=0.05) + walk(0.6, 3, 720, 1200, y=400))
fast = rule_zone_intrusion({3: p3}, ZONE)
check("intrusion: sub-dwell crossing fires nothing", len(fast) == 0,
      f"got {len(fast)}")

# ---------------------------------------------------------------- unattended object

BAG = dict(cx=500, cy=470, w=40, h=30)

# 4. bag put down at 5 s, owner leaves at 8 s and never returns (T = 10 s)
bag = make_track(10, 24, "backpack", still(4.0, 40.0, **BAG))
owner = make_track(11, PERSON_CLASS, "person",
                   walk(0, 5, 480, 500, y=500) + walk(5.1, 8, 500, 520, y=500)
                   + walk(8.1, 12, 540, 1200, y=500))
evs = rule_unattended_object({10: bag, 11: owner}, short_clip_mode=True)
check("unattended: abandoned bag fires one event", len(evs) == 1, f"got {len(evs)}")
if evs:
    ev = evs[0]
    check("unattended: owner and object are both cited",
          ev["owner_track_id"] == "TRK-11" and ev["object_track_id"] == "TRK-10")
    check("unattended: fires T seconds after the owner left",
          9.0 <= ev["t_start"] <= 22.0, f"t_start {ev['t_start']}s")
    check("unattended: thresholds recorded in the event",
          ev["thresholds"]["T_s"] == 10.0)

# 5. owner puts the bag down and stays beside it -> no event
owner_stays = make_track(21, PERSON_CLASS, "person", walk(0, 40, 480, 530, y=500))
bag5 = make_track(20, 24, "backpack", still(4.0, 40.0, **BAG))
evs5 = rule_unattended_object({20: bag5, 21: owner_stays}, short_clip_mode=True)
check("unattended: owner stays nearby, fires nothing", len(evs5) == 0, f"got {len(evs5)}")

# 6. owner leaves but comes back before T elapses -> no event
bag6 = make_track(30, 24, "backpack", still(4.0, 40.0, **BAG))
owner_returns = make_track(
    31, PERSON_CLASS, "person",
    walk(0, 8, 480, 520, y=500) + walk(8.1, 12, 540, 1000, y=500)
    + walk(12.1, 15, 1000, 520, y=500) + walk(15.1, 40, 520, 530, y=500))
evs6 = rule_unattended_object({30: bag6, 31: owner_returns}, short_clip_mode=True)
check("unattended: owner returns before T, fires nothing", len(evs6) == 0, f"got {len(evs6)}")

# 7. two people equally close when the bag goes down -> abstain, not a claim
bag7 = make_track(40, 26, "handbag", still(4.0, 40.0, **BAG))
a = make_track(41, PERSON_CLASS, "person", walk(0, 8, 470, 505, y=500) + walk(8.1, 12, 505, 1200, y=500))
b = make_track(42, PERSON_CLASS, "person", walk(0, 8, 530, 497, y=500) + walk(8.1, 12, 497, 1200, y=500))
evs7 = rule_unattended_object({40: bag7, 41: a, 42: b}, short_clip_mode=True)
ambiguous = [e for e in evs7 if e.get("owner_track_id") is None]
check("unattended: ambiguous ownership is flagged needs_review, not claimed",
      len(ambiguous) == 1 and ambiguous[0]["status"] == "needs_review",
      f"got {[(e.get('owner_track_id'), e.get('status')) for e in evs7]}")

# 8. a moving bag (carried the whole time) -> no event
bag8 = make_track(50, 28, "suitcase",
                  [(t, (100 + t * 20, 450, 140 + t * 20, 480)) for t in
                   [i / 10 for i in range(0, 400)]])
carrier = make_track(51, PERSON_CLASS, "person", walk(0, 39.9, 100, 900, y=500))
check("unattended: carried bag fires nothing",
      len(rule_unattended_object({50: bag8, 51: carrier}, short_clip_mode=True)) == 0)

# 9. a stale ghost closer to the bag than the live person is ignored
bag9 = make_track(60, 24, "backpack", still(10.0, 40.0, **BAG))
ghost = make_track(61, PERSON_CLASS, "person", [(0.0, (470, 390, 530, 550))])
live = make_track(62, PERSON_CLASS, "person",
                  walk(9.0, 12.0, 620, 640, y=500) + walk(12.1, 16.0, 700, 1400, y=500))
evs9 = rule_unattended_object({60: bag9, 61: ghost, 62: live}, short_clip_mode=True)
check("unattended: a stale ghost is not the owner and not a rival",
      len(evs9) == 1 and evs9[0]["owner_track_id"] == "TRK-62"
      and evs9[0]["status"] == "confirmed_by_rule" and "TRK-61" not in evs9[0]["track_ids"],
      f"got {[(e.get('owner_track_id'), e.get('status'), e.get('track_ids')) for e in evs9]}")

# 10. the live owner stays beside the bag -> no event
bag10 = make_track(70, 24, "backpack", still(10.0, 30.0, **BAG))
beside = make_track(71, PERSON_CLASS, "person", walk(9.0, 30.0, 500, 510, y=500))
check("unattended: a live owner staying near fires nothing",
      len(rule_unattended_object({70: bag10, 71: beside}, short_clip_mode=True)) == 0)

# 11. nobody is within owner_window_s of the moment the bag rests
bag11 = make_track(80, 24, "backpack", still(10.0, 25.0, **BAG))
absent = make_track(81, PERSON_CLASS, "person", [(0.0, (470, 390, 530, 550))])
evs11 = rule_unattended_object({80: bag11, 81: absent}, short_clip_mode=True)
check("unattended: no person at rest gives needs_review with a null owner",
      len(evs11) == 1 and evs11[0]["owner_track_id"] is None
      and evs11[0]["status"] == "needs_review"
      and "no person track was present near the bag when it came to rest" in evs11[0]["rule_trace"],
      f"got {[(e.get('owner_track_id'), e.get('status'), e.get('rule_trace')) for e in evs11]}")

# ---------------------------------------------------------------- validator

EVIDENCE = {
    "events": [{"event_id": "EV-0003", "t_start": 18.2, "t_end": 27.6,
                "status": "confirmed_by_rule"}],
    "tracks": [{"track_id": "TRK-7", "t_start": 2.0, "t_end": 30.0}],
}

good = {"decision": "yes", "abstained": False, "reason": "positive_evidence",
        "human_review_required": True,
        "claims": [{"text": "A person was inside zone Z1.",
                    "cited_ids": ["EV-0003"], "cited_time_range": [18.2, 27.6]}]}
ok, probs = validate(good, EVIDENCE)
check("validator: a well-formed cited answer passes", ok, str(probs))

hallucinated = {**good, "claims": [{"text": "x", "cited_ids": ["EV-0099"],
                                    "cited_time_range": [18.2, 27.6]}]}
ok, probs = validate(hallucinated, EVIDENCE)
check("validator: invented evidence ID is rejected", not ok, str(probs))

bad_time = {**good, "claims": [{"text": "x", "cited_ids": ["EV-0003"],
                                "cited_time_range": [5.0, 9.0]}]}
ok, probs = validate(bad_time, EVIDENCE)
check("validator: time outside the cited span is rejected", not ok, str(probs))

edge_time = {**good, "claims": [{"text": "x", "cited_ids": ["EV-0003"],
                                 "cited_time_range": [17.8, 28.0]}]}
ok, probs = validate(edge_time, EVIDENCE)
check("validator: time within the +/-0.5 s tolerance passes", ok, str(probs))

uncited = {**good, "claims": [{"text": "x", "cited_ids": [], "cited_time_range": [18.2, 27.6]}]}
check("validator: a claim with no citation is rejected", not validate(uncited, EVIDENCE)[0])

abstained_with_claims = {**good, "abstained": True, "reason": "insufficient_evidence"}
check("validator: an abstention carrying claims is rejected",
      not validate(abstained_with_claims, EVIDENCE)[0])

clean_abstention = {"decision": "cannot_determine", "abstained": True,
                    "reason": "insufficient_evidence", "claims": [],
                    "human_review_required": True}
ok, probs = validate(clean_abstention, EVIDENCE)
check("validator: a clean abstention passes", ok, str(probs))

no_flag = {**good, "human_review_required": False}
check("validator: human_review_required must be true",
      not validate(no_flag, EVIDENCE)[0])

review_evidence = {
    "events": [
        {"event_id": "EV-0001", "t_start": 26.0, "t_end": 33.8, "status": "needs_review"},
        {"event_id": "EV-0002", "t_start": 10.0, "t_end": 20.0, "status": "confirmed_by_rule"},
    ],
    "tracks": [],
}
only_review = {**good, "claims": [{"text": "A bag was left.", "cited_ids": ["EV-0001"],
                                   "cited_time_range": [26.0, 33.8]}]}
ok, probs = validate(only_review, review_evidence)
check("validator: positive_evidence citing only needs_review is rejected",
      not ok and any("confirmed_by_rule" in p for p in probs), str(probs))
confirmed = {**good, "claims": [{"text": "A bag was left.", "cited_ids": ["EV-0002"],
                                 "cited_time_range": [10.0, 20.0]}]}
ok, probs = validate(confirmed, review_evidence)
check("validator: positive_evidence citing a confirmed event passes", ok, str(probs))

eligible_evidence = {
    "events": [{"event_id": "EV-0003", "t_start": 18.2, "t_end": 27.6}],
    "tracks": [{"track_id": "TRK-7", "t_start": 2.0, "t_end": 30.0}],
    "coverage": {"unattended_object": [[0.0, 58.12]], "fall": []},
    "negative_eligible": {
        "unattended_object": True, "zone_intrusion": False, "fall": False,
    },
}
ineligible_evidence = {
    **eligible_evidence,
    "negative_eligible": {
        "unattended_object": False, "zone_intrusion": False, "fall": False,
    },
}
good_negative = {
    "decision": "no", "abstained": False, "reason": "verified_negative",
    "human_review_required": True,
    "claims": [{"text": "The unattended-object rule covered the clip and found no event.",
                "cited_ids": ["COV-unattended_object"], "cited_time_range": [0.0, 58.12]}],
}
ok, probs = validate(good_negative, eligible_evidence)
check("validator: an eligible verified_negative citing COV passes", ok, str(probs))

ok, probs = validate(good_negative, ineligible_evidence)
check("validator: verified_negative when not eligible is rejected",
      not ok and any("not eligible" in p for p in probs), str(probs))

trk_negative = {**good_negative, "claims": [
    {"text": "No bag was left.", "cited_ids": ["TRK-7"], "cited_time_range": [2.0, 30.0]}]}
ok, probs = validate(trk_negative, eligible_evidence)
check("validator: verified_negative citing a track instead of COV is rejected",
      not ok and any("COV-" in p for p in probs), str(probs))

outside_negative = {**good_negative, "claims": [
    {"text": "No bag was left.", "cited_ids": ["COV-unattended_object"],
     "cited_time_range": [70.0, 80.0]}]}
ok, probs = validate(outside_negative, eligible_evidence)
check("validator: a COV time range outside coverage is rejected",
      not ok and any("outside" in p for p in probs), str(probs))


def window_negative(start=None, end=None):
    claim = {
        "text": "The zone_intrusion rule found no zone intrusion in the cited window.",
        "cited_ids": ["COV-zone_intrusion"],
    }
    if start is not None:
        claim["cited_time_range"] = [start, end]
    return {
        "decision": "no", "abstained": False, "reason": "verified_negative",
        "human_review_required": True, "claims": [claim],
    }


def zone_window_evidence(events, eligible=True):
    return {
        "events": events,
        "tracks": [],
        "coverage": {"zone_intrusion": [[0.0, 26.079]]},
        "negative_eligible": {"zone_intrusion": eligible},
    }


ev_before_ten = {
    "event_id": "EV-0001", "type": "zone_intrusion",
    "t_start": 16.216, "t_end": 19.375, "status": "confirmed_by_rule",
}
ok, probs = validate(window_negative(0, 10), zone_window_evidence([ev_before_ten]))
check("validator: window no 0-10 before EV-0001 passes", ok, str(probs))

ok, probs = validate(window_negative(0, 17), zone_window_evidence([ev_before_ten]))
check("validator: window 0-17 overlapping EV-0001 is rejected",
      not ok and any("overlaps EV-0001" in p for p in probs), str(probs))

ok, probs = validate(window_negative(20, 26), zone_window_evidence([ev_before_ten]))
check("validator: window 20-26 after EV-0001 passes", ok, str(probs))

ok, probs = validate(window_negative(20, 30), zone_window_evidence([ev_before_ten]))
check("validator: window 20-30 past coverage is rejected", not ok, str(probs))

ok, probs = validate(window_negative(0.0, 26.079), zone_window_evidence([]))
check("validator: full-clip no with no events passes", ok, str(probs))

ok, probs = validate(window_negative(), zone_window_evidence([ev_before_ten]))
check("validator: full-clip no with no cited range is rejected when EV-0001 exists",
      not ok and any("overlaps EV-0001" in p for p in probs), str(probs))

for status in ("candidate", "needs_review"):
    overlapping = {**ev_before_ten, "status": status}
    ok, probs = validate(window_negative(16, 20), zone_window_evidence([overlapping]))
    check(f"validator: {status} event overlapping the window is rejected",
          not ok and any("overlaps EV-0001" in p for p in probs), str(probs))

ok, probs = validate(window_negative(0, 10), zone_window_evidence([ev_before_ten], eligible=False))
check("validator: window no when not eligible is rejected",
      not ok and any("not eligible" in p for p in probs), str(probs))

# ---------------------------------------------------------------- API error class


class _StatusError(Exception):
    def __init__(self, code: int):
        super().__init__(f"HTTP {code}")
        self.code = code


check("api error: HTTP 404 is fatal",
      classify_api_error(_StatusError(404)) == "fatal")
check("api error: HTTP 503 is transient",
      classify_api_error(_StatusError(503)) == "transient")
check("api error: HTTP 429 is transient",
      classify_api_error(_StatusError(429)) == "transient")
check("api error: JSON parse error is bad_output",
      classify_api_error(json.JSONDecodeError("Expecting value", "", 0)) == "bad_output")

# ---------------------------------------------------------------- display label and short tracks

mixed = Track(7, 26, "handbag")
for i, (label, cls, conf) in enumerate(
    [("handbag", 26, 0.91), ("suitcase", 28, 0.55), ("suitcase", 28, 0.50)]
    + [("backpack", 24, 0.62)] * 4
):
    mixed.dets.append(Detection(
        frame_idx=i, t_s=round(i / FPS, 3), track_id=7, cls=cls, label=label,
        conf=conf, bbox=(0, 0, 10, 10),
    ))
check("label: mixed track takes the majority label",
      majority_label(mixed) == "backpack", majority_label(mixed))
check("label: class_votes count every detection",
      class_votes(mixed) == {"backpack": 4, "handbag": 1, "suitcase": 2},
      str(class_votes(mixed)))

box = (0, 0, 10, 10)
long_track = make_track(1, 0, "person", [(i / FPS, box) for i in range(6)])
short_track = make_track(2, 24, "backpack", [(i / FPS, box) for i in range(3)])
cited_short = make_track(3, 26, "handbag", [(i / FPS, box) for i in range(3)])
kept_boundary = make_track(4, 24, "backpack", [(i / FPS, box) for i in range(5)])
shown, n_omitted = visible_tracks(
    [long_track, short_track, cited_short, kept_boundary],
    [{"track_ids": ["TRK-3"], "object_track_id": "TRK-3", "owner_track_id": None}],
    THRESHOLDS["min_track_frames"],
)
shown_ids = [t.track_id for t in shown]
check("short tracks: a 3-frame track is omitted", 2 not in shown_ids, str(shown_ids))
check("short tracks: a cited 3-frame track is kept", 3 in shown_ids, str(shown_ids))
check("short tracks: omitted count is the tracks left out",
      n_omitted == 1 and shown_ids == [1, 3, 4],
      f"count={n_omitted} ids={shown_ids}")

# ---------------------------------------------------------------- report

width = max(len(name) for _, name, _ in results) + 2
failed = 0
print()
for status, name, detail in results:
    if status == FAIL:
        failed += 1
    print(f"  {status}  {name.ljust(width)}{detail if status == FAIL else ''}")
print(f"\n{len(results) - failed}/{len(results)} checks passed\n")
sys.exit(1 if failed else 0)
