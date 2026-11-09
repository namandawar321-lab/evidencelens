"""Record a clip from the laptop webcam.

Usage:
    python record_clip.py --seconds 20 --out-dir data/clips

The preview is not mirrored. Saved frames do not include the countdown or the
REC marker. Pure helpers at the top do not open a camera.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

WARMUP_FRAMES = 10
DEFAULT_SECONDS = 20.0
MAX_RECORD_S = 60.0
MAX_DURATION_S = 120.0
MAX_WIDTH = 1280
MAX_HEIGHT = 720
WINDOW = "EvidenceLens record"


def measured_fps(frames_written: int, elapsed_s: float) -> float | None:
    """Frames written divided by elapsed seconds. None when either is not positive."""
    if frames_written <= 0 or elapsed_s <= 0:
        return None
    return float(frames_written) / float(elapsed_s)


def clamp_record_seconds(seconds: float) -> float:
    """Recording length: at least 1 s, at most 60 s. The default request is 20 s."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return DEFAULT_SECONDS
    if value != value:  # NaN
        return DEFAULT_SECONDS
    return max(1.0, min(value, MAX_RECORD_S))


def live_clip_name(when: datetime) -> str:
    """File stem live_yyyymmdd_hhmmss. The clock is the caller's; this does not read the camera."""
    return "live_" + when.strftime("%Y%m%d_%H%M%S")


def rejection_reason(duration_s: float, width: int, height: int) -> str | None:
    """None when the clip may be processed. Over 2 minutes or over 720p is refused."""
    try:
        duration = float(duration_s)
        wide = int(width)
        high = int(height)
    except (TypeError, ValueError):
        return "The clip duration or resolution could not be read."
    if duration > MAX_DURATION_S:
        return (
            f"This clip is {duration:.1f} s long. "
            "Clips over 2 minutes are not accepted."
        )
    if wide > MAX_WIDTH or high > MAX_HEIGHT:
        return (
            f"This clip is {wide}×{high}. "
            "Clips over 720p (1280×720) are not accepted."
        )
    return None


def consent_refusal(checked: bool, licence: str) -> str | None:
    """None when processing is allowed. A missing tick or an empty licence refuses it."""
    if not checked:
        return "Tick the box that people in this clip have consented, or that you own this clip, before processing."
    if not str(licence).strip():
        return "Enter a licence in the text box before processing."
    return None


def csv_field(value: str) -> str:
    """Quote a CSV field so a comma or a quote inside it cannot split the row."""
    text = str(value).replace("\r", " ").replace("\n", " ").replace('"', '""')
    return f'"{text}"'


def licence_log_row(
    clip_id: str,
    source: str,
    licence: str,
    url: str,
    downloaded_on: str,
    allowed_in_public_demo: str,
) -> str:
    return ",".join(
        csv_field(item)
        for item in (clip_id, source, licence, url, downloaded_on, allowed_in_public_demo)
    )


def _even(frame):
    height, width = frame.shape[:2]
    width -= width % 2
    height -= height % 2
    if width < 2 or height < 2:
        return None
    return frame[:height, :width]


def _preview(frame, text: str, recording: bool):
    import cv2

    canvas = frame.copy()
    if recording:
        cv2.circle(canvas, (28, 28), 12, (0, 0, 255), -1)
        cv2.putText(canvas, "REC", (48, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas, text, (16, canvas.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    return canvas


def _show(canvas) -> int:
    import cv2

    cv2.imshow(WINDOW, canvas)
    return cv2.waitKey(1) & 0xFF


def open_camera():
    """Default capture, then DirectShow on Windows if that did not open."""
    import cv2

    capture = cv2.VideoCapture(0)
    if capture.isOpened():
        return capture
    capture.release()
    if sys.platform == "win32":
        capture = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if capture.isOpened():
            return capture
        capture.release()
    return None


def _hold(capture, text: str, seconds: float) -> bool:
    """Show the latest frame for `seconds`. Return False if the user presses q."""
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        ok, frame = capture.read()
        if not ok or frame is None:
            continue
        shown = _even(frame)
        if shown is None:
            continue
        if _show(_preview(shown, text, False)) == ord("q"):
            return False
    return True


def _ffmpeg_cfr(source: Path, dest: Path, fps: float) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg is not on PATH, so the clip was not re-encoded for playback.")
    command = [
        ffmpeg, "-y",
        "-i", str(source),
        "-r", f"{fps:.6f}",
        "-fps_mode", "cfr",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-an",
        str(dest),
    ]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
        raise SystemExit("ffmpeg could not write the H.264 clip.")


def record_to(out_dir: Path, seconds: float, when: datetime | None = None) -> tuple[Path, float, int, float]:
    """Record, write at the measured fps, then re-encode. Returns path, fps, frames, elapsed."""
    import cv2

    seconds = clamp_record_seconds(seconds)
    when = when or datetime.now()
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{live_clip_name(when)}.mp4"
    capture = open_camera()
    if capture is None:
        raise SystemExit("The webcam did not open.")
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    frames = []
    elapsed = 0.0
    try:
        for _ in range(WARMUP_FRAMES):
            capture.read()
        for count in (3, 2, 1):
            if not _hold(capture, str(count), 1.0):
                raise SystemExit("Stopped during the countdown. Nothing was saved.")
        start = time.perf_counter()
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            clean = _even(frame)
            if clean is None:
                break
            frames.append(clean.copy())
            elapsed = time.perf_counter() - start
            label = f"{elapsed:5.1f} s"
            if _show(_preview(clean, label, True)) == ord("q"):
                break
            if elapsed >= seconds:
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()
    if not frames or elapsed <= 0:
        raise SystemExit("No frames were recorded.")
    fps = measured_fps(len(frames), elapsed)
    if fps is None:
        raise SystemExit("The frame rate could not be measured.")
    height, width = frames[0].shape[:2]
    temp = dest.with_suffix(".tmp.avi")
    writer = cv2.VideoWriter(str(temp), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    if not writer.isOpened():
        raise SystemExit("The temporary recording file could not be opened.")
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()
    try:
        _ffmpeg_cfr(temp, dest, fps)
    except SystemExit:
        dest.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)
    print(f"fps={fps:.6f}")
    print(f"frames={len(frames)}")
    print(f"elapsed_s={elapsed:.6f}")
    print(f"wrote={dest}")
    return dest, fps, len(frames), elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a webcam clip for EvidenceLens")
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--out-dir", default="data/clips")
    args = parser.parse_args()
    record_to(Path(args.out_dir), args.seconds)


if __name__ == "__main__":
    main()
