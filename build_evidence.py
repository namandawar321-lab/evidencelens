"""EvidenceLens POC - offline stage.

clip -> YOLO11 detection -> ByteTrack -> rule engine -> evidence.json + keyframes

Usage:
    python build_evidence.py data/clips/office_door_03.mp4
    python build_evidence.py data/clips/leftbag_01.mp4 --short-clip-mode
    python build_evidence.py data/clips/door.mp4 --zone data/zones/door.json

Output: data/evidence/<clip_stem>/evidence.json and frames/*.jpg

Every threshold below comes from the requirements doc (Section 3, "Event definitions").
They are design assumptions to be tuned on the development split and then frozen.
No part of this file calls an LLM. Timestamps are computed from frame indices only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

# ---------------------------------------------------------------- configuration

RULE_VERSIONS = {"zone_intrusion": "v1", "fall": "v1", "unattended_object": "v1"}

# COCO class ids used by the pre-trained YOLO11 weights
PERSON_CLASS = 0
BAG_CLASSES = {24: "backpack", 26: "handbag", 28: "suitcase"}
TRACK_CLASSES = [PERSON_CLASS, *BAG_CLASSES]

THRESHOLDS = {
    "det_conf_min": 0.4,            # minimum detection confidence (both rules)
    "intrusion_dwell_s": 1.0,       # foot point inside the polygon for this long
    "intrusion_exit_s": 1.0,        # outside for this long before the event ends
    "intrusion_merge_gap_s": 2.0,   # same-track events closer than this are merged
    "static_window_s": 3.0,         # window used to decide a bag is static
    "static_move_frac": 0.05,       # centre moves < 5% of the box diagonal
    "owner_away_height_mult": 1.5,  # owner further than 1.5x their box height
    "owner_return_height_mult": 1.0,
    "owner_window_s": 2.0,          # a person must be seen within this of t_static
    "unattended_T_s": 30.0,         # 10.0 in short-clip mode
    "unattended_T_s_short": 10.0,
    "min_track_frames": 5,          # omit shorter tracks from evidence unless an event cites them
}


# ---------------------------------------------------------------- data classes

@dataclass
class Detection:
    frame_idx: int
    t_s: float
    track_id: int
    cls: int
    label: str
    conf: float
    bbox: tuple[float, float, float, float]  # xyxy

    @property
    def centre(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @property
    def foot_point(self) -> tuple[float, float]:
        x1, _, x2, y2 = self.bbox
        return ((x1 + x2) / 2, y2)

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def diagonal(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return float(np.hypot(x2 - x1, y2 - y1))


@dataclass
class Track:
    track_id: int
    cls: int
    label: str
    dets: list[Detection] = field(default_factory=list)

    @property
    def t_start(self) -> float:
        return self.dets[0].t_s

    @property
    def t_end(self) -> float:
        return self.dets[-1].t_s

    @property
    def mean_conf(self) -> float:
        return float(np.mean([d.conf for d in self.dets]))

    def at(self, frame_idx: int) -> Detection | None:
        for d in self.dets:
            if d.frame_idx == frame_idx:
                return d
        return None

    def fragmented(self, stride: int) -> bool:
        """True if the track has a gap of more than 5 sampled steps."""
        idxs = [d.frame_idx for d in self.dets]
        return any(b - a > 5 * stride for a, b in zip(idxs, idxs[1:]))


def class_votes(track: Track) -> dict[str, int]:
    """How many detections on this track carry each label."""
    counts: dict[str, int] = {}
    for det in track.dets:
        counts[det.label] = counts.get(det.label, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def majority_label(track: Track) -> str:
    """Most common detection label.

    A tie goes to the label with the higher mean confidence. If those means
    are also equal, the label of the earliest detection wins.
    """
    if not track.dets:
        return track.label
    votes = class_votes(track)
    totals: dict[str, float] = {}
    first_at: dict[str, int] = {}
    for i, det in enumerate(track.dets):
        totals[det.label] = totals.get(det.label, 0.0) + det.conf
        first_at.setdefault(det.label, i)

    def rank(label: str) -> tuple:
        n = votes[label]
        return (n, totals[label] / n, -first_at[label])

    return max(votes, key=rank)


def cited_track_ids(events: list[dict]) -> set[int]:
    cited: set[int] = set()
    for event in events:
        raws = list(event.get("track_ids") or [])
        for key in ("object_track_id", "owner_track_id"):
            raw = event.get(key)
            if raw:
                raws.append(raw)
        for raw in raws:
            text = str(raw)
            if text.startswith("TRK-"):
                text = text[4:]
            cited.add(int(text))
    return cited


def coverage_spans_clip(ranges, duration_s: float) -> bool:
    """True when the ranges together cover the clip from 0 to duration_s."""
    if duration_s <= 0 or not ranges:
        return False
    spans = sorted((float(start), float(end)) for start, end in ranges)
    cursor = 0.0
    eps = 1e-3
    for start, end in spans:
        if start > cursor + eps:
            return False
        if end > cursor:
            cursor = end
    return cursor + eps >= float(duration_s)


def visible_tracks(tracks, events: list[dict], min_frames: int) -> tuple[list[Track], int]:
    """Tracks written to evidence, and how many short tracks were left out.

    Does not run the rules. A track with fewer than min_frames detections is
    omitted unless an event cites it. The caller still runs rules on every track.
    """
    if isinstance(tracks, dict):
        items = list(tracks.values())
    else:
        items = list(tracks)
    cited = cited_track_ids(events)
    visible: list[Track] = []
    omitted = 0
    for track in items:
        if len(track.dets) < min_frames and track.track_id not in cited:
            omitted += 1
            continue
        visible.append(track)
    return visible, omitted


# ---------------------------------------------------------------- helpers

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def video_meta(path: Path) -> dict:
    cap = cv2.VideoCapture(str(path))
    meta = {
        "fps_native": cap.get(cv2.CAP_PROP_FPS),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "resolution": [int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                       int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))],
    }
    cap.release()
    meta["duration_s"] = round(meta["frame_count"] / meta["fps_native"], 3) if meta["fps_native"] else 0.0
    return meta


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def save_keyframes(clip: Path, frame_idxs: list[int], out_dir: Path, prefix: str) -> list[str]:
    """Pull specific frames out of the clip and write them as JPEGs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(clip))
    paths = []
    for tag, idx in frame_idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(idx, 0))
        ok, frame = cap.read()
        if not ok:
            continue
        name = f"{prefix}_{tag}.jpg"
        cv2.imwrite(str(out_dir / name), frame)
        paths.append(f"frames/{name}")
    cap.release()
    return paths


# ---------------------------------------------------------------- detection and tracking

def run_tracking(clip: Path, weights: str, target_fps: float, fps_native: float,
                 imgsz: int) -> tuple[dict[int, Track], int, dict]:
    """Returns {track_id: Track}, the frame stride used, and provenance info."""
    from ultralytics import YOLO

    stride = max(1, round(fps_native / target_fps)) if fps_native else 1
    model = YOLO(weights)

    tracks: dict[int, Track] = {}
    step = 0
    for result in model.track(
        source=str(clip),
        tracker="bytetrack.yaml",
        classes=TRACK_CLASSES,
        conf=THRESHOLDS["det_conf_min"],
        imgsz=imgsz,
        vid_stride=stride,
        persist=True,
        stream=True,
        verbose=False,
    ):
        frame_idx = step * stride
        step += 1
        boxes = result.boxes
        if boxes is None or boxes.id is None:
            continue
        for tid, cls, conf, xyxy in zip(
            boxes.id.int().tolist(),
            boxes.cls.int().tolist(),
            boxes.conf.tolist(),
            boxes.xyxy.tolist(),
        ):
            label = "person" if cls == PERSON_CLASS else BAG_CLASSES.get(cls, str(cls))
            det = Detection(
                frame_idx=frame_idx,
                t_s=round(frame_idx / fps_native, 3),
                track_id=tid,
                cls=cls,
                label=label,
                conf=round(float(conf), 3),
                bbox=tuple(round(v, 1) for v in xyxy),
            )
            tracks.setdefault(tid, Track(tid, cls, label)).dets.append(det)

    provenance = {
        "detector": "ultralytics-yolo11",
        "weights": weights,
        "tracker": "bytetrack.yaml",
        "imgsz": imgsz,
        "conf_threshold": THRESHOLDS["det_conf_min"],
        "fps_processed": round(fps_native / stride, 3) if fps_native else None,
        "frame_stride": stride,
        "code_commit": git_commit(),
        "run_time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return tracks, stride, provenance


# ---------------------------------------------------------------- rule: zone intrusion

def rule_zone_intrusion(tracks: dict[int, Track], zone: dict) -> list[dict]:
    """Foot point inside the polygon for >= dwell; ends after >= exit outside."""
    poly = np.array(zone["polygon"], dtype=np.int32)
    dwell = THRESHOLDS["intrusion_dwell_s"]
    exit_s = THRESHOLDS["intrusion_exit_s"]
    events: list[dict] = []

    for track in tracks.values():
        if track.cls != PERSON_CLASS:
            continue

        spans: list[list] = []          # [t_in, t_last_inside, frame_in, frame_last]
        open_span = None
        last_inside_t = None

        for det in track.dets:
            inside = cv2.pointPolygonTest(poly, det.foot_point, False) >= 0
            if inside:
                if open_span is None:
                    open_span = [det.t_s, det.t_s, det.frame_idx, det.frame_idx]
                open_span[1], open_span[3] = det.t_s, det.frame_idx
                last_inside_t = det.t_s
            elif open_span is not None and last_inside_t is not None:
                if det.t_s - last_inside_t >= exit_s:
                    spans.append(open_span)
                    open_span = None
        if open_span is not None:
            spans.append(open_span)

        # merge spans of the same track that are close together
        merged: list[list] = []
        for span in spans:
            if merged and span[0] - merged[-1][1] < THRESHOLDS["intrusion_merge_gap_s"]:
                merged[-1][1], merged[-1][3] = span[1], span[3]
            else:
                merged.append(span)

        for t_in, t_out, f_in, f_out in merged:
            if t_out - t_in < dwell:
                continue
            events.append({
                "type": "zone_intrusion",
                "t_start": round(t_in, 3),
                "t_end": round(t_out, 3),
                "track_ids": [f"TRK-{track.track_id}"],
                "zone_id": zone["zone_id"],
                "rule_id": "zone_intrusion",
                "rule_version": RULE_VERSIONS["zone_intrusion"],
                "thresholds": {
                    "dwell_min_s": dwell,
                    "exit_min_s": exit_s,
                    "conf_min": THRESHOLDS["det_conf_min"],
                },
                "rule_trace": (
                    f"foot point of TRK-{track.track_id} inside zone {zone['zone_id']} "
                    f"from {t_in:.1f}s to {t_out:.1f}s (dwell {t_out - t_in:.1f}s, "
                    f"minimum {dwell:.1f}s), detection conf >= {THRESHOLDS['det_conf_min']}"
                ),
                "confidence": round(track.mean_conf, 3),
                "_frames": [("start", f_in), ("end", f_out)],
            })
    return events


# ---------------------------------------------------------------- rule: unattended object

def _static_from(bag: Track, t_window: float) -> tuple[float, int] | None:
    """First time the bag centre stays within static_move_frac of its diagonal."""
    for i, det in enumerate(bag.dets):
        window = [d for d in bag.dets[i:] if d.t_s - det.t_s <= t_window]
        if not window or window[-1].t_s - det.t_s < t_window * 0.8:
            continue
        cx, cy = det.centre
        moved = max(np.hypot(d.centre[0] - cx, d.centre[1] - cy) for d in window)
        if moved < THRESHOLDS["static_move_frac"] * det.diagonal:
            return det.t_s, det.frame_idx
    return None


def rule_unattended_object(tracks: dict[int, Track], short_clip_mode: bool) -> list[dict]:
    T = THRESHOLDS["unattended_T_s_short"] if short_clip_mode else THRESHOLDS["unattended_T_s"]
    persons = [t for t in tracks.values() if t.cls == PERSON_CLASS]
    events: list[dict] = []

    for bag in tracks.values():
        if bag.cls not in BAG_CLASSES:
            continue
        static = _static_from(bag, THRESHOLDS["static_window_s"])
        if static is None:
            continue
        t_static, f_static = static
        bdet = bag.at(f_static)

        # owner = person nearest to the bag's box at t_static, seen within owner_window_s
        window = THRESHOLDS["owner_window_s"]
        candidates: list[tuple[Track, float]] = []
        for person in persons:
            close = [d for d in person.dets if abs(d.t_s - t_static) <= window]
            if not close:
                continue
            pdet = min(close, key=lambda d: (abs(d.t_s - t_static), d.frame_idx))
            dist = float(np.hypot(pdet.centre[0] - bdet.centre[0],
                                  pdet.centre[1] - bdet.centre[1]))
            candidates.append((person, dist))
        if not candidates:
            events.append({
                "type": "unattended_object",
                "t_start": round(t_static, 3),
                "t_end": round(bag.t_end, 3),
                "track_ids": [f"TRK-{bag.track_id}"],
                "object_track_id": f"TRK-{bag.track_id}",
                "owner_track_id": None,
                "rule_id": "unattended_object",
                "rule_version": RULE_VERSIONS["unattended_object"],
                "thresholds": {"T_s": T},
                "rule_trace": (
                    f"TRK-{bag.track_id}: no person track was present near the bag "
                    f"when it came to rest"
                ),
                "confidence": round(bag.mean_conf, 3),
                "status": "needs_review",
                "_frames": [("static", f_static)],
            })
            continue
        owner, best_dist = min(candidates, key=lambda item: (item[1], item[0].track_id))

        # ambiguous ownership: another candidate was about as close
        rivals = sum(
            1 for person, dist in candidates
            if person.track_id != owner.track_id and dist < best_dist * 1.2
        )
        if rivals:
            events.append({
                "type": "unattended_object",
                "t_start": round(t_static, 3),
                "t_end": round(bag.t_end, 3),
                "track_ids": [f"TRK-{bag.track_id}"],
                "object_track_id": f"TRK-{bag.track_id}",
                "owner_track_id": None,
                "rule_id": "unattended_object",
                "rule_version": RULE_VERSIONS["unattended_object"],
                "thresholds": {"T_s": T},
                "rule_trace": (
                    f"owner association uncertain for TRK-{bag.track_id}: "
                    f"{rivals + 1} person tracks were within 20% of the same distance "
                    f"at {t_static:.1f}s"
                ),
                "confidence": round(bag.mean_conf, 3),
                "status": "needs_review",
                "_frames": [("static", f_static)],
            })
            continue

        # when did the owner get far away (or disappear)?
        away_from, away_frame = None, None
        for bdet in bag.dets:
            if bdet.t_s < t_static:
                continue
            odet = owner.at(bdet.frame_idx)
            if odet is None:
                if bdet.t_s > owner.t_end:          # owner track lost
                    away_from, away_frame = bdet.t_s, bdet.frame_idx
                    break
                continue
            dist = float(np.hypot(odet.centre[0] - bdet.centre[0],
                                  odet.centre[1] - bdet.centre[1]))
            if dist > THRESHOLDS["owner_away_height_mult"] * odet.height:
                away_from, away_frame = bdet.t_s, bdet.frame_idx
                break
        if away_from is None:
            continue   # the owner stayed with the bag: correctly no event

        # did the owner come back before T elapsed?
        returned = False
        for bdet in bag.dets:
            if not (away_from < bdet.t_s <= away_from + T):
                continue
            odet = owner.at(bdet.frame_idx)
            if odet and float(np.hypot(odet.centre[0] - bdet.centre[0],
                                       odet.centre[1] - bdet.centre[1])) \
                    <= THRESHOLDS["owner_return_height_mult"] * odet.height:
                returned = True
                break
        if returned:
            continue

        t_fire = away_from + T
        if t_fire > bag.t_end:
            continue   # the clip ends before T elapses: no event, coverage says why

        fire_frame = next((d.frame_idx for d in bag.dets if d.t_s >= t_fire), bag.dets[-1].frame_idx)
        events.append({
            "type": "unattended_object",
            "t_start": round(t_fire, 3),
            "t_end": round(bag.t_end, 3),
            "track_ids": [f"TRK-{bag.track_id}", f"TRK-{owner.track_id}"],
            "object_track_id": f"TRK-{bag.track_id}",
            "owner_track_id": f"TRK-{owner.track_id}",
            "rule_id": "unattended_object",
            "rule_version": RULE_VERSIONS["unattended_object"],
            "thresholds": {
                "T_s": T,
                "static_window_s": THRESHOLDS["static_window_s"],
                "static_move_frac": THRESHOLDS["static_move_frac"],
                "owner_away_height_mult": THRESHOLDS["owner_away_height_mult"],
            },
            "rule_trace": (
                f"TRK-{bag.track_id} ({majority_label(bag)}) static from {t_static:.1f}s; "
                f"owner TRK-{owner.track_id} further than "
                f"{THRESHOLDS['owner_away_height_mult']}x box height from {away_from:.1f}s "
                f"and did not return within T={T:.0f}s; event fires at {t_fire:.1f}s"
            ),
            "confidence": round(min(bag.mean_conf, owner.mean_conf), 3),
            "status": "confirmed_by_rule",
            "_frames": [("static", f_static), ("owner_away", away_frame), ("fire", fire_frame)],
        })
    return events


# ---------------------------------------------------------------- assembly

def build(clip: Path, out_root: Path, weights: str, target_fps: float,
          zone_path: Path | None, short_clip_mode: bool, imgsz: int,
          licence: str, consent_basis: str, source_dataset: str) -> Path:
    meta = video_meta(clip)
    print(f"[1/5] {clip.name}: {meta['resolution'][0]}x{meta['resolution'][1]}, "
          f"{meta['fps_native']:.2f} fps, {meta['duration_s']:.1f}s")

    print("[2/5] detection and tracking ...")
    tracks, stride, provenance = run_tracking(clip, weights, target_fps, meta["fps_native"], imgsz)
    n_person = sum(1 for t in tracks.values() if t.cls == PERSON_CLASS)
    n_bag = sum(1 for t in tracks.values() if t.cls in BAG_CLASSES)
    print(f"      {len(tracks)} tracks ({n_person} person, {n_bag} bag)")

    zone = json.loads(zone_path.read_text()) if zone_path else None

    print("[3/5] rules ...")
    events: list[dict] = []
    if zone:
        events += rule_zone_intrusion(tracks, zone)
    events += rule_unattended_object(tracks, short_clip_mode)
    for i, ev in enumerate(sorted(events, key=lambda e: e["t_start"]), start=1):
        ev["event_id"] = f"EV-{i:04d}"
        ev.setdefault("status", "confirmed_by_rule")
    events = sorted(events, key=lambda e: e["t_start"])
    print(f"      {len(events)} event(s): " +
          (", ".join(f"{e['event_id']} {e['type']} {e['t_start']}-{e['t_end']}s"
                     for e in events) or "none"))

    out_dir = out_root / clip.stem
    frames_dir = out_dir / "frames"
    print("[4/5] keyframes ...")
    for ev in events:
        ev["supporting_frames"] = save_keyframes(clip, ev.pop("_frames"), frames_dir, ev["event_id"])

    coverage = {
        "unattended_object": [[0.0, meta["duration_s"]]],
        **({"zone_intrusion": [[0.0, meta["duration_s"]]]} if zone else {}),
        "fall": [],   # the fall rule is not implemented in the POC
    }
    # Counts are from every track, before short tracks are omitted from the file.
    # Bag and person use the track's class id, the same filter the rules use.
    duration = meta["duration_s"]
    negative_eligible = {
        "unattended_object": coverage_spans_clip(coverage["unattended_object"], duration) and n_bag >= 1,
        "zone_intrusion": (
            zone is not None
            and coverage_spans_clip(coverage.get("zone_intrusion") or [], duration)
            and n_person >= 1
        ),
        "fall": False,
    }
    detector_summary = {"bag_tracks": n_bag, "person_tracks": n_person}
    shown, n_omitted = visible_tracks(tracks, events, THRESHOLDS["min_track_frames"])

    evidence = {
        "schema_version": "2.0-poc",
        "video": {
            "video_id": clip.stem,
            "camera_id": zone["camera_id"] if zone else clip.stem,
            "source_dataset": source_dataset,
            "licence": licence,
            "consent_basis": consent_basis,
            "fps_native": round(meta["fps_native"], 3),
            "fps_processed": provenance["fps_processed"],
            "frame_count": meta["frame_count"],
            "duration_s": meta["duration_s"],
            "resolution": meta["resolution"],
            "sha256": sha256_of(clip),
        },
        "zones": [zone] if zone else [],
        "tracks": [
            {
                "track_id": f"TRK-{t.track_id}",
                "class": majority_label(t),
                "class_votes": class_votes(t),
                "t_start": round(t.t_start, 3),
                "t_end": round(t.t_end, 3),
                "n_frames": len(t.dets),
                "mean_conf": round(t.mean_conf, 3),
                "fragmented": t.fragmented(stride),
                "keypoints_available": False,
            }
            for t in sorted(shown, key=lambda t: t.track_id)
        ],
        "tracks_omitted_short": {
            "count": n_omitted,
            "min_frames": THRESHOLDS["min_track_frames"],
        },
        "events": events,
        "coverage": coverage,
        "negative_eligible": negative_eligible,
        "detector_summary": detector_summary,
        "provenance": provenance,
        "limits": [
            "single fixed camera; distances are in owner-height units (uncalibrated)",
            "rule thresholds are design assumptions, not tuned",
            "no identification of people; no intent, guilt or medical inference",
        ],
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "evidence.json"
    out_path.write_text(json.dumps(evidence, indent=2))
    print(f"[5/5] wrote {out_path}")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="EvidenceLens POC offline stage")
    ap.add_argument("clip")
    ap.add_argument("--out-root", default="data/evidence")
    ap.add_argument("--weights", default="yolo11s.pt")
    ap.add_argument("--fps", type=float, default=10.0, help="target processing FPS")
    ap.add_argument("--imgsz", type=int, default=960, help="raise to 1280 for small bags")
    ap.add_argument("--zone", default=None, help="zone JSON from draw_zone.py")
    ap.add_argument("--short-clip-mode", action="store_true",
                    help="use T = 10 s instead of 30 s for unattended objects")
    ap.add_argument("--licence", default="unverified")
    ap.add_argument("--consent-basis", default="n/a")
    ap.add_argument("--source-dataset", default="unknown")
    args = ap.parse_args()

    build(
        clip=Path(args.clip),
        out_root=Path(args.out_root),
        weights=args.weights,
        target_fps=args.fps,
        zone_path=Path(args.zone) if args.zone else None,
        short_clip_mode=args.short_clip_mode,
        imgsz=args.imgsz,
        licence=args.licence,
        consent_basis=args.consent_basis,
        source_dataset=args.source_dataset,
    )


if __name__ == "__main__":
    main()
