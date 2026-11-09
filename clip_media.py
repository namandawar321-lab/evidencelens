"""Presentation media for the demo.

Writes an H.264 event extract and, when it can, an annotated clip.
Does not change detection results. A new clip_path is the only evidence field added.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVIDENCE_ROOT = ROOT / "data" / "evidence"
CLIPS_ROOT = ROOT / "data" / "clips"
ANNOTATED_ROOT = ROOT / "data" / "annotated"


def ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def event_window(event: dict, duration_s: float | None) -> tuple[float, float]:
    start = max(0.0, float(event.get("t_start") or 0) - 3.0)
    end = float(event.get("t_end") or 0) + 3.0
    if duration_s is not None:
        end = min(end, float(duration_s))
    if end < start:
        end = start
    return start, end


def _save_clip_path(clip_id: str, event_id: str, relative: str) -> None:
    path = EVIDENCE_ROOT / clip_id / "evidence.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    for event in evidence.get("events") or []:
        if event.get("event_id") == event_id:
            event["clip_path"] = relative
            break
    path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")


def ensure_event_clip(clip_id: str, evidence: dict, event: dict) -> tuple[Path | None, str | None]:
    """Return the +/- 3 s extract. Write it once and store clip_path."""
    event_id = str(event.get("event_id") or "")
    relative = event.get("clip_path")
    if relative:
        existing = EVIDENCE_ROOT / clip_id / relative
        if existing.is_file() and existing.stat().st_size > 0:
            return existing, None
    source = CLIPS_ROOT / f"{clip_id}.mp4"
    if not source.is_file():
        return None, "The source clip is not in data/clips."
    ffmpeg = ffmpeg_bin()
    if ffmpeg is None:
        return None, "ffmpeg is not on PATH, so the +/- 3 s extract was not written."
    duration = (evidence.get("video") or {}).get("duration_s")
    start, end = event_window(event, float(duration) if duration is not None else None)
    length = max(0.1, end - start)
    relative = f"clips/{event_id}.mp4"
    dest = EVIDENCE_ROOT / clip_id / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg, "-y",
        "-ss", f"{start:.3f}",
        "-i", str(source),
        "-t", f"{length:.3f}",
        "-fps_mode", "cfr",
        "-vf", "format=yuv420p",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-an",
        str(dest),
    ]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0 or not dest.is_file():
        return None, "ffmpeg could not write the +/- 3 s extract. Showing the full clip instead."
    event["clip_path"] = relative
    _save_clip_path(clip_id, event_id, relative)
    return dest, None


def annotated_path(clip_id: str) -> Path:
    return ANNOTATED_ROOT / f"{clip_id}.mp4"


def ensure_annotated(clip_id: str, evidence: dict) -> tuple[Path | None, str | None]:
    """Draw boxes from a fresh track pass using the build's detector settings.

    Saved evidence has no box coordinates. If this pass fails or is unavailable,
    the caller shows the plain clip.
    """
    dest = annotated_path(clip_id)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest, None
    source = CLIPS_ROOT / f"{clip_id}.mp4"
    if not source.is_file():
        return None, "The source clip is not in data/clips. Showing no annotated video."
    ffmpeg = ffmpeg_bin()
    if ffmpeg is None:
        return None, "ffmpeg is not on PATH. Showing the plain clip."
    try:
        import cv2
        import numpy as np
        from ultralytics import YOLO
        from build_evidence import THRESHOLDS, TRACK_CLASSES
    except Exception as exc:
        return None, f"The overlay could not start ({type(exc).__name__}). Showing the plain clip."

    weights = ROOT / "yolo11s.pt"
    if not weights.is_file():
        return None, "yolo11s.pt is missing. Showing the plain clip."

    capture = cv2.VideoCapture(str(source))
    fps_native = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    capture.release()
    if width < 2 or height < 2 or not fps_native:
        return None, "The clip could not be read. Showing the plain clip."
    width -= width % 2
    height -= height % 2
    stride = max(1, round(fps_native / 10.0))
    out_fps = fps_native / stride
    zones = []
    for zone in evidence.get("zones") or []:
        poly = zone.get("polygon") if isinstance(zone, dict) else None
        if poly and len(poly) >= 3:
            zones.append(np.array(poly, dtype=np.int32))
    confirmed = []
    for event in evidence.get("events") or []:
        if event.get("status") == "confirmed_by_rule":
            confirmed.append((float(event.get("t_start") or 0), float(event.get("t_end") or 0), str(event.get("event_id") or "")))

    ANNOTATED_ROOT.mkdir(parents=True, exist_ok=True)
    raw = dest.with_suffix(".tmp.avi")
    writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"MJPG"), out_fps, (width, height))
    if not writer.isOpened():
        return None, "The overlay file could not be opened. Showing the plain clip."
    try:
        model = YOLO(str(weights))
        for step, result in enumerate(model.track(
            source=str(source),
            tracker="bytetrack.yaml",
            classes=TRACK_CLASSES,
            conf=THRESHOLDS["det_conf_min"],
            imgsz=960,
            vid_stride=stride,
            persist=True,
            stream=True,
            verbose=False,
        )):
            frame = result.orig_img
            if frame is None:
                continue
            frame = frame[:height, :width].copy()
            t_s = (step * stride) / fps_native
            for poly in zones:
                cv2.polylines(frame, [poly], True, (0, 220, 255), 2)
            boxes = result.boxes
            if boxes is not None and len(boxes) > 0 and boxes.id is not None:
                classes = boxes.cls.int().tolist() if boxes.cls is not None else [0] * len(boxes)
                for tid, xyxy, cls in zip(boxes.id.int().tolist(), boxes.xyxy.tolist(), classes):
                    x1, y1, x2, y2 = [int(round(v)) for v in xyxy]
                    color = (0, 160, 0) if cls == 0 else (255, 140, 0)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(
                        frame, f"TRK-{tid}", (x1, max(14, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA,
                    )
            hit = [name for start, end, name in confirmed if start <= t_s <= end]
            if hit:
                cv2.rectangle(frame, (2, 2), (width - 3, height - 3), (0, 140, 255), 4)
                cv2.putText(
                    frame, "confirmed " + ", ".join(hit), (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 140, 255), 1, cv2.LINE_AA,
                )
            writer.write(frame)
    except Exception as exc:
        writer.release()
        raw.unlink(missing_ok=True)
        return None, f"The overlay stopped ({type(exc).__name__}). Showing the plain clip."
    writer.release()
    command = [
        ffmpeg, "-y", "-i", str(raw),
        "-fps_mode", "cfr", "-vf", "format=yuv420p",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(dest),
    ]
    done = subprocess.run(command, capture_output=True, text=True)
    raw.unlink(missing_ok=True)
    if done.returncode != 0 or not dest.is_file():
        dest.unlink(missing_ok=True)
        return None, "ffmpeg could not finish the annotated video. Showing the plain clip."
    return dest, None
