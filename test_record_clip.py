"""Pure checks for recording helpers. No camera, GPU or API key.

    python test_record_clip.py
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from record_clip import (
    consent_refusal,
    csv_field,
    clamp_record_seconds,
    licence_log_row,
    live_clip_name,
    measured_fps,
    rejection_reason,
)

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((PASS if condition else FAIL, name, detail))


def test_fps() -> None:
    rate = measured_fps(30, 1.5)
    check("fps is frames divided by elapsed seconds", rate == 20.0, str(rate))
    check("fps is undefined without frames", measured_fps(0, 2.0) is None)
    check("fps is undefined without elapsed time", measured_fps(10, 0.0) is None)


def test_name() -> None:
    name = live_clip_name(datetime(2026, 10, 30, 10, 9, 5))
    check("live clip name is live_yyyymmdd_hhmmss", name == "live_20261030_100905", name)


def test_record_limit() -> None:
    check("default record length stays 20 s", clamp_record_seconds(20) == 20.0)
    check("record length caps at 60 s", clamp_record_seconds(90) == 60.0)
    check("a blank record length falls back to 20 s", clamp_record_seconds("nope") == 20.0)


def test_clip_limits() -> None:
    check("2 minutes at 720p is accepted", rejection_reason(120.0, 1280, 720) is None)
    over_time = rejection_reason(120.1, 640, 480) or ""
    check("over 2 minutes is refused", "over 2 minutes" in over_time, over_time)
    over_size = rejection_reason(10.0, 1920, 1080) or ""
    check("over 720p is refused", "over 720p" in over_size, over_size)
    tall = rejection_reason(10.0, 1280, 721) or ""
    check("height over 720 is refused", "over 720p" in tall, tall)


def test_consent() -> None:
    missing_tick = consent_refusal(False, "I own this clip") or ""
    check("processing is refused without the consent tick", "Tick the box" in missing_tick)
    missing_text = consent_refusal(True, "   ") or ""
    check("processing is refused without a licence", "licence" in missing_text)
    check("consent and a licence allow processing", consent_refusal(True, "operator owned") is None)


def test_csv_quoting() -> None:
    licence = 'CC BY, "personal" recording'
    row = licence_log_row("live_20261030_100905", "webcam", licence, "", "2026-10-30", "no, local only")
    parsed = next(csv.reader(io.StringIO(row)))
    check("a comma inside the licence stays in one field", parsed[2] == licence, parsed[2])
    check("every licence-log field is quoted", row.count('"' ) >= 12)
    check("csv_field doubles an internal quote", '""personal""' in csv_field(licence))


def main() -> None:
    test_fps()
    test_name()
    test_record_limit()
    test_clip_limits()
    test_consent()
    test_csv_quoting()
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
