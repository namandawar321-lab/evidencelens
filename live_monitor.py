"""Provisional live preview. The language model is not in this loop.

The window draws the latest person and bag tracks. The authoritative evidence
is the recording, passed afterwards through build_evidence.py. Nothing here
calls Gemini or edits a rule.

Usage:
    python live_monitor.py --max-seconds 100 --licence "..." --consent-basis "..."
    python live_monitor.py --grab-still data/zones/stills/live_still.mp4
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from build_evidence import BAG_CLASSES, PERSON_CLASS, THRESHOLDS, TRACK_CLASSES
from record_clip import (
    _even,
    _ffmpeg_cfr,
    licence_log_row,
    live_clip_name,
    MAX_DURATION_S,
    measured_fps,
    open_camera,
    rejection_reason,
)

ROOT = Path(__file__).resolve().parent
MAX_SESSION_S = 100.0
TRIM_S = 115.0
AUTO_STOP_TEXT = "Auto-stops at 100 s"
WINDOW_HINT = "Press q or click Stop to finish. Auto-stops at 100 s."
# Display inference only. The batch build is not given these sizes.
DISPLAY_IMGSZ = 960
DISPLAY_IMGSZ_FAST = 640
FPS_FLOOR = 10.0
WINDOW = "EvidenceLens live"


def foot_point(bbox) -> tuple[float, float]:
    """Bottom-centre of an xyxy box. Same point the batch zone rule uses."""
    x1, _y1, x2, y2 = bbox
    return ((float(x1) + float(x2)) / 2.0, float(y2))


def foot_inside(polygon, foot: tuple[float, float]) -> bool:
    """cv2.pointPolygonTest, the same test rule_zone_intrusion uses (>= 0 is inside)."""
    import cv2
    import numpy as np

    poly = np.array(polygon, dtype=np.int32)
    return cv2.pointPolygonTest(poly, (float(foot[0]), float(foot[1])), False) >= 0


def update_dwell(
    state: dict,
    track_id: int,
    t_s: float,
    inside: bool,
    dwell_s: float,
    exit_s: float,
) -> tuple[bool, float]:
    """Provisional banner for one track. Display only; this does not write an event.

    A span runs from the first inside sample to the latest inside sample. A gap
    shorter than the batch exit time keeps that span. A gap at or beyond it
    clears the span, so the next entry starts again.
    """
    row = state.get(track_id)
    if row is None:
        row = {"t_in": None, "t_last": None}
        state[track_id] = row
    if inside:
        if row["t_in"] is None:
            row["t_in"] = t_s
        row["t_last"] = t_s
    elif row["t_in"] is not None and row["t_last"] is not None:
        if t_s - row["t_last"] >= exit_s:
            row["t_in"] = None
            row["t_last"] = None
    if row["t_in"] is None or row["t_last"] is None:
        return False, 0.0
    span = float(row["t_last"]) - float(row["t_in"])
    return span >= dwell_s, span


def provisional_banners(boxes: list, fps: float, polygon, dwell_s: float, exit_s: float) -> list[bool]:
    """One banner flag per box. A missing box is outside. No camera."""
    if fps <= 0:
        return []
    state: dict = {}
    flags: list[bool] = []
    for index, box in enumerate(boxes):
        inside = box is not None and foot_inside(polygon, foot_point(box))
        alerting, _span = update_dwell(state, 1, index / fps, inside, dwell_s, exit_s)
        flags.append(alerting)
    return flags


def adapt_detection(fps: float, every: int, imgsz: int) -> tuple[int, int, str]:
    """Lighten display detection when the rate is below 10. Never used for the batch build."""
    if fps >= FPS_FLOOR:
        return every, imgsz, ""
    if every < 2:
        return 2, imgsz, "every second frame"
    if imgsz > DISPLAY_IMGSZ_FAST:
        return every, DISPLAY_IMGSZ_FAST, "smaller inference size"
    return every, imgsz, "every second frame"


def clamp_session_seconds(seconds: float) -> float:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return MAX_SESSION_S
    if value != value:
        return MAX_SESSION_S
    return max(1.0, min(value, MAX_SESSION_S))


def stop_flag_path(root: Path) -> Path:
    return Path(root) / "data" / "live_stop.flag"


def stop_requested(path: Path) -> bool:
    return Path(path).is_file()


def request_stop(path: Path) -> None:
    """The app writes this file. The live window checks it every frame."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stop\n", encoding="utf-8")


def clear_stop_flag(path: Path) -> None:
    Path(path).unlink(missing_ok=True)


def window_closed(visible: float) -> bool:
    """OpenCV reports a value below 1 after the X button closes the window."""
    try:
        return float(visible) < 1
    except (TypeError, ValueError):
        return False


def needs_duration_trim(duration_s: float) -> bool:
    """True when the file is over the upload limit. 120.0 s is still accepted."""
    try:
        duration = float(duration_s)
    except (TypeError, ValueError):
        return False
    return duration > MAX_DURATION_S


class LatestFrame:
    """The capture thread keeps one frame. Older frames are dropped."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame = None
        self._seq = 0

    def put(self, frame) -> None:
        with self._lock:
            self._frame = frame
            self._seq += 1

    def get(self):
        with self._lock:
            if self._frame is None:
                return None, 0
            return self._frame.copy(), self._seq


def _capture_loop(capture, latest: LatestFrame, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            ok, frame = capture.read()
        except Exception:
            break
        if not ok or frame is None:
            continue
        frame = _even(frame)
        if frame is None:
            continue
        latest.put(frame.copy())


def _detector_device() -> tuple[object, str]:
    import torch

    if torch.cuda.is_available():
        return 0, f"cuda ({torch.cuda.get_device_name(0)})"
    return "cpu", "cpu"


def _load_model(weights: Path, device, imgsz: int):
    import numpy as np
    from ultralytics import YOLO

    model = YOLO(str(weights))
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    tracked = model.track(
        source=dummy,
        tracker="bytetrack.yaml",
        classes=TRACK_CLASSES,
        conf=THRESHOLDS["det_conf_min"],
        imgsz=imgsz,
        persist=True,
        verbose=False,
        device=device,
    )
    if tracked is None:
        raise SystemExit("The detector warm-up did not return a frame.")
    return model


def _parse_boxes(result) -> list[dict]:
    boxes = getattr(result, "boxes", None)
    if boxes is None or boxes.id is None:
        return []
    parsed = []
    for tid, cls, conf, xyxy in zip(
        boxes.id.int().tolist(),
        boxes.cls.int().tolist(),
        boxes.conf.tolist(),
        boxes.xyxy.tolist(),
    ):
        label = "person" if cls == PERSON_CLASS else BAG_CLASSES.get(cls, str(cls))
        parsed.append({
            "tid": int(tid),
            "cls": int(cls),
            "label": label,
            "conf": float(conf),
            "xyxy": tuple(float(v) for v in xyxy),
        })
    return parsed


def _detect_loop(
    model,
    latest: LatestFrame,
    stop: threading.Event,
    started: float,
    polygon,
    shared: dict,
    device,
) -> None:
    dwell_s = THRESHOLDS["intrusion_dwell_s"]
    exit_s = THRESHOLDS["intrusion_exit_s"]
    state: dict = {}
    every = 1
    imgsz = DISPLAY_IMGSZ
    notes: list[str] = []
    latencies: list[float] = []
    detect_started = time.perf_counter()
    detections = 0
    seen_seq = 0
    skip = 0
    last_adapt_at = 0
    while not stop.is_set():
        frame, seq = latest.get()
        if frame is None or seq == seen_seq:
            time.sleep(0.005)
            continue
        seen_seq = seq
        skip += 1
        if skip % every != 0:
            continue
        t0 = time.perf_counter()
        try:
            tracked = model.track(
                source=frame,
                tracker="bytetrack.yaml",
                classes=TRACK_CLASSES,
                conf=THRESHOLDS["det_conf_min"],
                imgsz=imgsz,
                persist=True,
                verbose=False,
                device=device,
            )
            result = tracked[0] if isinstance(tracked, list) else tracked
        except Exception as exc:
            with shared["lock"]:
                shared["error"] = f"{type(exc).__name__}: {exc}"
            return
        latencies.append(time.perf_counter() - t0)
        detections += 1
        parsed = _parse_boxes(result)
        t_s = time.perf_counter() - started
        alerts = []
        seen_ids = set()
        for box in parsed:
            if box["cls"] != PERSON_CLASS or polygon is None:
                continue
            inside = foot_inside(polygon, foot_point(box["xyxy"]))
            alerting, span = update_dwell(state, box["tid"], t_s, inside, dwell_s, exit_s)
            seen_ids.add(box["tid"])
            if alerting:
                alerts.append((box["tid"], span))
        if polygon is not None:
            for tid in list(state):
                if tid in seen_ids:
                    continue
                alerting, span = update_dwell(state, tid, t_s, False, dwell_s, exit_s)
                if alerting:
                    alerts.append((tid, span))
        rate = detections / max(time.perf_counter() - detect_started, 1e-6)
        if detections >= 5 and detections - last_adapt_at >= 5 and (time.perf_counter() - detect_started) >= 1.0:
            new_every, new_imgsz, note = adapt_detection(rate, every, imgsz)
            if (new_every, new_imgsz) != (every, imgsz):
                last_adapt_at = detections
                if note and note not in notes:
                    notes.append(note)
                    print(f"adapt={note}", flush=True)
            every, imgsz = new_every, new_imgsz
        with shared["lock"]:
            shared["boxes"] = parsed
            shared["alerts"] = alerts
            shared["latencies"] = list(latencies)
            shared["detect_fps"] = rate
            shared["adapt"] = "; ".join(notes) if notes else "none"
            shared["imgsz"] = imgsz


def _draw(frame, boxes, alerts, polygon, fps: float, elapsed: float, adapt: str):
    import cv2
    import numpy as np

    canvas = frame.copy()
    if polygon and len(polygon) >= 3:
        pts = np.array(polygon, dtype=np.int32)
        cv2.polylines(canvas, [pts], isClosed=True, color=(0, 220, 0), thickness=2)
    for box in boxes:
        x1, y1, x2, y2 = (int(v) for v in box["xyxy"])
        colour = (255, 160, 0) if box["label"] == "person" else (0, 200, 255)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), colour, 2)
        cv2.putText(
            canvas,
            f"{box['label']} {box['tid']}",
            (x1, max(16, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            colour,
            1,
            cv2.LINE_AA,
        )
    top = 0
    if alerts:
        width = canvas.shape[1]
        cv2.rectangle(canvas, (0, 0), (width, 52), (0, 0, 180), -1)
        parts = " ".join(f"TRK-{tid} {span:.1f}s" for tid, span in alerts)
        cv2.putText(
            canvas,
            "ZONE INTRUSION (provisional, live preview)",
            (8, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(canvas, parts, (8, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        top = 56
    cv2.circle(canvas, (28, top + 28), 12, (0, 0, 255), -1)
    cv2.putText(canvas, "REC", (48, top + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
    cv2.putText(
        canvas,
        f"{elapsed:5.1f} s",
        (110, top + 36),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        f"{fps:4.1f} fps",
        (16, top + 64),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    if adapt and adapt != "none":
        cv2.putText(
            canvas,
            adapt,
            (16, top + 88),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 255, 0),
            1,
            cv2.LINE_AA,
        )
    height, width = canvas.shape[:2]
    cv2.rectangle(canvas, (0, height - 28), (width, height), (0, 0, 0), -1)
    cv2.putText(
        canvas,
        WINDOW_HINT,
        (8, height - 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return canvas


def _append_licence(row: str) -> None:
    path = ROOT / "licence_log.csv"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(row + "\n")


def _load_polygon(zone_path: str | None):
    if not zone_path:
        return None
    path = Path(zone_path)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    polygon = data.get("polygon") if isinstance(data, dict) else None
    if not polygon or len(polygon) < 3:
        return None
    return polygon


def grab_still(dest: Path) -> Path:
    """One current view, repeated for 1 second, so draw_zone.py can open it."""
    import cv2

    dest = dest if dest.suffix.lower() == ".mp4" else dest.with_suffix(".mp4")
    dest.parent.mkdir(parents=True, exist_ok=True)
    capture = open_camera()
    if capture is None:
        raise SystemExit("The webcam did not open.")
    frame = None
    try:
        for _ in range(10):
            capture.read()
        for _ in range(30):
            ok, frame = capture.read()
            if ok and frame is not None:
                break
    finally:
        capture.release()
    frame = _even(frame) if frame is not None else None
    if frame is None:
        raise SystemExit("The webcam did not return a frame.")
    height, width = frame.shape[:2]
    temp = dest.with_suffix(".tmp.avi")
    writer = cv2.VideoWriter(str(temp), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (width, height))
    if not writer.isOpened():
        raise SystemExit("The still clip could not be opened.")
    try:
        for _ in range(10):
            writer.write(frame)
    finally:
        writer.release()
    try:
        _ffmpeg_cfr(temp, dest, 10.0)
    except SystemExit:
        dest.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)
    print(f"wrote={dest}", flush=True)
    return dest


def _run_build(clip: Path, zone: str | None, licence: str, consent: str) -> int:
    command = [
        sys.executable,
        str(ROOT / "build_evidence.py"),
        str(clip),
        "--short-clip-mode",
        "--licence",
        licence,
        "--consent-basis",
        consent,
        "--source-dataset",
        "webcam",
    ]
    if zone and Path(zone).is_file():
        command.extend(["--zone", zone])
    print("stage=Detecting...", flush=True)
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log: list[str] = []
    building = False
    if proc.stdout is not None:
        for line in proc.stdout:
            log.append(line)
            if not building and "[3/5]" in line:
                building = True
                print("stage=Building evidence...", flush=True)
    code = proc.wait()
    if code != 0:
        sys.stdout.write("".join(log[-30:]))
        return code
    if not building:
        print("stage=Building evidence...", flush=True)
    return 0


def _prepare_media(clip_id: str) -> None:
    from clip_media import ensure_annotated, ensure_event_clip

    evidence_path = ROOT / "data" / "evidence" / clip_id / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    try:
        _path, note = ensure_annotated(clip_id, evidence)
        if note:
            print(note, flush=True)
        for event in evidence.get("events") or []:
            _extract, event_note = ensure_event_clip(clip_id, evidence, event)
            if event_note:
                print(f"{event.get('event_id')}: {event_note}", flush=True)
    except Exception as exc:
        print(f"The annotated video was not written ({type(exc).__name__}).", flush=True)


def _ffmpeg_measured(source: Path, dest: Path, fps: float) -> None:
    """Read every stored frame at the measured rate, then write H.264 constant frame rate.

    The temporary file uses a placeholder rate so it can be written while the
    camera is open. -r is placed before -i so ffmpeg does not resample that rate.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg is not on PATH, so the clip was not re-encoded for playback.")
    command = [
        ffmpeg, "-y",
        "-r", f"{fps:.6f}",
        "-i", str(source),
        "-fps_mode", "cfr",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-an",
        str(dest),
    ]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
        raise SystemExit("ffmpeg could not write the H.264 clip.")


def _trim_duration(path: Path, seconds: float) -> None:
    """Keep the file. Cut it to the first `seconds` instead of rejecting it."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg is not on PATH, so the long clip was kept and not trimmed.")
    trimmed = path.with_name(path.stem + "_trim.mp4")
    command = [
        ffmpeg, "-y", "-i", str(path),
        "-t", f"{seconds:.3f}",
        "-fps_mode", "cfr",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-an",
        str(trimmed),
    ]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0 or not trimmed.is_file() or trimmed.stat().st_size <= 0:
        trimmed.unlink(missing_ok=True)
        raise SystemExit("The clip was over 2 minutes and could not be trimmed. The file was kept.")
    trimmed.replace(path)


def _finish_recording(temp: Path, dest: Path, frames: int, elapsed: float, zone: str | None, licence: str, consent: str) -> None:
    fps = measured_fps(frames, elapsed)
    if fps is None:
        raise SystemExit("The frame rate could not be measured.")
    print("stage=Saving...", flush=True)
    try:
        _ffmpeg_measured(temp, dest, fps)
    except SystemExit:
        dest.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)
    import cv2

    probe = cv2.VideoCapture(str(dest))
    width = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    file_fps = float(probe.get(cv2.CAP_PROP_FPS) or 0)
    file_frames = float(probe.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    probe.release()
    duration = file_frames / file_fps if file_fps > 0 else elapsed
    if needs_duration_trim(duration):
        _trim_duration(dest, TRIM_S)
        print(
            "trimmed=This clip was over 2 minutes, so it was trimmed to the first 115 s.",
            flush=True,
        )
        probe = cv2.VideoCapture(str(dest))
        width = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        file_fps = float(probe.get(cv2.CAP_PROP_FPS) or 0)
        file_frames = float(probe.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        probe.release()
        duration = file_frames / file_fps if file_fps > 0 else TRIM_S
    refused = rejection_reason(duration, width, height)
    if refused:
        raise SystemExit(refused)
    _append_licence(licence_log_row(
        dest.stem,
        "webcam",
        licence,
        "",
        datetime.now().date().isoformat(),
        "no, local only",
    ))
    code = _run_build(dest, zone, licence, consent)
    if code != 0:
        raise SystemExit(f"build_evidence.py failed ({code}).")
    _prepare_media(dest.stem)
    print("stage=Ready", flush=True)
    print(f"wrote={dest}", flush=True)


def run_monitor(out_dir: Path, seconds: float, zone: str | None, licence: str, consent: str, when: datetime | None = None) -> Path:
    import cv2

    flag = stop_flag_path(ROOT)
    clear_stop_flag(flag)
    if not str(licence).strip() or not str(consent).strip():
        raise SystemExit("A licence and a consent basis are required before the live monitor starts.")
    weights = ROOT / "yolo11s.pt"
    if not weights.is_file():
        raise SystemExit("yolo11s.pt is missing.")
    seconds = clamp_session_seconds(seconds)
    polygon = _load_polygon(zone)
    device, device_label = _detector_device()
    print(f"device={device_label}", flush=True)
    model = _load_model(weights, device, DISPLAY_IMGSZ)
    capture = open_camera()
    if capture is None:
        raise SystemExit("The webcam did not open.")
    try:
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    for _ in range(10):
        capture.read()
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{live_clip_name(when or datetime.now())}.mp4"
    temp = dest.with_suffix(".tmp.avi")
    latest = LatestFrame()
    stop = threading.Event()
    shared = {
        "lock": threading.Lock(),
        "boxes": [],
        "alerts": [],
        "latencies": [],
        "detect_fps": 0.0,
        "adapt": "none",
        "imgsz": DISPLAY_IMGSZ,
        "error": "",
    }
    started = time.perf_counter()
    capture_thread = threading.Thread(target=_capture_loop, args=(capture, latest, stop), daemon=True)
    detect_thread = threading.Thread(
        target=_detect_loop,
        args=(model, latest, stop, started, polygon, shared, device),
        daemon=True,
    )
    capture_thread.start()
    detect_thread.start()
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    writer = None
    frames = 0
    last_seq = 0
    raw = None
    recorded_s = 0.0
    shown = False
    try:
        while True:
            recorded_s = time.perf_counter() - started
            if recorded_s >= seconds or stop_requested(flag):
                break
            frame, seq = latest.get()
            if frame is not None and seq != last_seq:
                last_seq = seq
                raw = frame
                if writer is None:
                    height, width = frame.shape[:2]
                    writer = cv2.VideoWriter(str(temp), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (width, height))
                    if not writer.isOpened():
                        raise SystemExit("The temporary recording file could not be opened.")
                writer.write(frame)
                frames += 1
                with shared["lock"]:
                    boxes = list(shared["boxes"])
                    alerts = list(shared["alerts"])
                    adapt = shared["adapt"]
                    error = shared["error"]
                if error:
                    raise SystemExit(error)
                rate = measured_fps(frames, recorded_s) or 0.0
                try:
                    cv2.imshow(WINDOW, _draw(raw, boxes, alerts, polygon, rate, recorded_s, adapt))
                except cv2.error:
                    break
                shown = True
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            if shown:
                try:
                    visible = cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE)
                except cv2.error:
                    break
                if window_closed(visible):
                    break
            if frame is None or seq == last_seq:
                time.sleep(0.005)
    finally:
        clear_stop_flag(flag)
        stop.set()
        capture.release()
        capture_thread.join(timeout=2)
        detect_thread.join(timeout=2)
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()
    elapsed = recorded_s
    with shared["lock"]:
        latencies = list(shared["latencies"])
        detect_fps = float(shared["detect_fps"])
        adapt = shared["adapt"]
    fps = measured_fps(frames, elapsed)
    mean_ms = (sum(latencies) / len(latencies) * 1000.0) if latencies else 0.0
    max_ms = (max(latencies) * 1000.0) if latencies else 0.0
    print(f"fps={fps:.6f}" if fps is not None else "fps=", flush=True)
    print(f"detect_fps={detect_fps:.3f}", flush=True)
    print(f"latency_ms={mean_ms:.2f}", flush=True)
    print(f"latency_max_ms={max_ms:.2f}", flush=True)
    print(f"adapt={adapt}", flush=True)
    print(f"frames={frames}", flush=True)
    print(f"elapsed_s={elapsed:.6f}", flush=True)
    if frames <= 0 or fps is None:
        temp.unlink(missing_ok=True)
        raise SystemExit("No frames were recorded.")
    _finish_recording(temp, dest, frames, elapsed, zone if polygon is not None else None, licence, consent)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description="Provisional webcam preview, then the normal evidence build.")
    parser.add_argument("--max-seconds", type=float, default=MAX_SESSION_S)
    parser.add_argument("--out-dir", default="data/clips")
    parser.add_argument("--zone", default=None)
    parser.add_argument("--licence", default="")
    parser.add_argument("--consent-basis", default="")
    parser.add_argument("--grab-still", default=None, help="Save a 1-second still clip and exit.")
    args = parser.parse_args()
    if args.grab_still:
        grab_still(Path(args.grab_still))
        return
    run_monitor(
        Path(args.out_dir),
        args.max_seconds,
        args.zone,
        args.licence,
        args.consent_basis,
    )


if __name__ == "__main__":
    main()
