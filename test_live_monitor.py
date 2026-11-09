"""Provisional dwell timer. No camera, GPU or API key.

    python test_live_monitor.py
"""

from __future__ import annotations

import math

import tempfile
from pathlib import Path

from build_evidence import THRESHOLDS
from live_monitor import (
    AUTO_STOP_TEXT,
    MAX_SESSION_S,
    TRIM_S,
    WINDOW_HINT,
    clamp_session_seconds,
    clear_stop_flag,
    foot_inside,
    foot_point,
    needs_duration_trim,
    provisional_banners,
    request_stop,
    stop_requested,
    window_closed,
)
from record_clip import MAX_DURATION_S

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []

POLYGON = [[0, 0], [200, 0], [200, 200], [0, 200]]
INSIDE = (40, 20, 80, 100)
OUTSIDE = (40, 20, 80, 260)
FOOT_OUT_OVERLAP = (40, 150, 80, 250)
FPS = 10.0


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((PASS if condition else FAIL, name, detail))


def _trigger_index(dwell_s: float, fps: float) -> int:
    return math.ceil(dwell_s * fps - 1e-9)


def _exit_steps(exit_s: float, fps: float) -> int:
    return math.ceil(exit_s * fps - 1e-9)


def test_foot() -> None:
    check("foot point is the bottom centre", foot_point((40, 20, 80, 100)) == (60.0, 100.0))
    check("a foot inside the square is inside", foot_inside(POLYGON, foot_point(INSIDE)))
    check("a foot below the square is outside", not foot_inside(POLYGON, foot_point(OUTSIDE)))
    check(
        "a box that overlaps the square is outside when the foot is outside",
        not foot_inside(POLYGON, foot_point(FOOT_OUT_OVERLAP)),
    )


def test_dwell_triggers_at_threshold() -> None:
    dwell = THRESHOLDS["intrusion_dwell_s"]
    exit_s = THRESHOLDS["intrusion_exit_s"]
    trigger = _trigger_index(dwell, FPS)
    boxes = [INSIDE] * (trigger + 1)
    flags = provisional_banners(boxes, FPS, POLYGON, dwell, exit_s)
    check("nothing before the dwell", flags[:trigger] == [False] * trigger, str(flags[:trigger]))
    check("the banner starts at the dwell", flags[trigger] is True, f"index {trigger} t={trigger / FPS}")


def test_leaving_resets() -> None:
    dwell = THRESHOLDS["intrusion_dwell_s"]
    exit_s = THRESHOLDS["intrusion_exit_s"]
    trigger = _trigger_index(dwell, FPS)
    steps = _exit_steps(exit_s, FPS)
    inside_run = [INSIDE] * (trigger + 1)
    outside_run = [OUTSIDE] * steps
    fresh = [INSIDE] * trigger
    flags = provisional_banners(inside_run + outside_run + fresh, FPS, POLYGON, dwell, exit_s)
    clear_at = trigger + steps
    check("the banner is on before the exit gap ends", flags[clear_at - 1] is True)
    check("leaving for the exit gap clears the banner", flags[clear_at] is False, f"index {clear_at}")
    check("a new visit shorter than the dwell stays clear", flags[clear_at + 1:] == [False] * trigger)


def test_short_exit_does_not_reset() -> None:
    dwell = THRESHOLDS["intrusion_dwell_s"]
    exit_s = THRESHOLDS["intrusion_exit_s"]
    trigger = _trigger_index(dwell, FPS)
    check("one frame is shorter than the exit gap", (1 / FPS) < exit_s)
    early = [INSIDE] * trigger
    flags = provisional_banners(early + [OUTSIDE, INSIDE], FPS, POLYGON, dwell, exit_s)
    check("a short visit does not alert before the dwell", flags[:trigger] == [False] * trigger)
    check("the short outside frame does not alert on its own", flags[trigger] is False)
    check("the same span alerts when the foot returns", flags[trigger + 1] is True)
    held = provisional_banners([INSIDE] * (trigger + 3) + [OUTSIDE], FPS, POLYGON, dwell, exit_s)
    check("a short exit does not clear a banner that already started", held[-1] is True)


def test_session_limit() -> None:
    check("the live auto-stop is 100 s", MAX_SESSION_S == 100.0)
    check("a 120 s request is capped at 100 s", clamp_session_seconds(120) == 100.0)
    check("100 s is kept", clamp_session_seconds(100) == 100.0)
    check("a shorter session is kept", clamp_session_seconds(20) == 20.0)
    check("the window names the 100 s stop", AUTO_STOP_TEXT == "Auto-stops at 100 s")
    check(
        "the window hint tells the user how to finish",
        WINDOW_HINT == "Press q or click Stop to finish. Auto-stops at 100 s.",
    )


def test_stop_flag() -> None:
    folder = Path(tempfile.mkdtemp())
    flag = folder / "nested" / "live_stop.flag"
    check("a missing stop flag does not stop", stop_requested(flag) is False)
    request_stop(flag)
    check("writing the stop flag requests a stop", stop_requested(flag) is True and flag.read_text(encoding="utf-8") == "stop\n")
    clear_stop_flag(flag)
    check("the stop flag is deleted after use", flag.exists() is False and stop_requested(flag) is False)
    clear_stop_flag(flag)
    check("deleting a missing stop flag does nothing", flag.exists() is False)


def test_over_limit_trim() -> None:
    check("the kept length is 115 s", TRIM_S == 115.0)
    check("120.0 s is accepted", needs_duration_trim(MAX_DURATION_S) is False)
    check("a clip just over 120 s is trimmed, not discarded", needs_duration_trim(MAX_DURATION_S + 0.03) is True)
    check("115 s does not need a trim", needs_duration_trim(TRIM_S) is False)


def test_window_close() -> None:
    check("the X button reports the window closed", window_closed(-1) is True and window_closed(0) is True)
    check("a visible window stays open", window_closed(1) is False)


def test_overlap_without_the_foot_does_not_alert() -> None:
    dwell = THRESHOLDS["intrusion_dwell_s"]
    exit_s = THRESHOLDS["intrusion_exit_s"]
    trigger = _trigger_index(dwell, FPS)
    flags = provisional_banners([FOOT_OUT_OVERLAP] * (trigger + 5), FPS, POLYGON, dwell, exit_s)
    check("the banner stays off when only the box overlaps", flags == [False] * len(flags))


def main() -> None:
    test_foot()
    test_dwell_triggers_at_threshold()
    test_leaving_resets()
    test_short_exit_does_not_reset()
    test_overlap_without_the_foot_does_not_alert()
    test_session_limit()
    test_stop_flag()
    test_over_limit_trim()
    test_window_close()
    failed = 0
    for status, name, detail in results:
        line = f"{status}: {name}"
        if detail:
            line += f" — {detail}"
        print(line)
        if status == FAIL:
            failed += 1
    print(f"{len(results) - failed}/{len(results)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
