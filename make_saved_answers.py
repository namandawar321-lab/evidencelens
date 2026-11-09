"""Build data/saved_answers/manifest.json from scratch demo console logs.

Reads the saved console logs only. Does not call Gemini and does not change
any answer text.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT.parent / "scratch" / "demo" / "demo_outputs"
OUT = ROOT / "data" / "saved_answers" / "manifest.json"

# Suffix after _q<digit>_ in the log file name.
QUESTION_BY_SUFFIX = {
    "q1_unattended": "Was an object left unattended?",
    "q2_intent": "Why did he leave the bag?",
    "q3_zone": "Did anyone enter a restricted area?",
    "q4_fall": "Did anyone fall?",
}

NAME = re.compile(r"^(?P<clip>.+)_q(?P<num>\d+)_(?P<suffix>[^.]+)\.txt$")


def read_log(path: Path) -> str:
    """Console logs were saved as UTF-16 by PowerShell. Do not rewrite them."""
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def extract_answer(text: str) -> tuple[str, dict] | None:
    """Split a console log into the lines before the JSON object, and the object.

    The JSON block starts at the line whose text is exactly '{'.
    """
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip() == "{":
            log = "".join(lines[:index])
            answer = json.loads("".join(lines[index:]))
            if not isinstance(answer, dict):
                return None
            return log, answer
    return None


def build_rows(log_dir: Path = LOG_DIR) -> list[dict]:
    rows: list[dict] = []
    if not log_dir.is_dir():
        return rows
    for path in sorted(log_dir.glob("*.txt")):
        match = NAME.match(path.name)
        if match is None:
            continue
        suffix = f"q{match.group('num')}_{match.group('suffix')}"
        question = QUESTION_BY_SUFFIX.get(suffix)
        if question is None:
            continue
        parsed = extract_answer(read_log(path))
        if parsed is None:
            raise SystemExit(f"{path.name}: no JSON object starting with a line '{{'")
        console_log, answer = parsed
        modified = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        rows.append(
            {
                "clip_id": match.group("clip"),
                "question": question,
                "answer_json": answer,
                "console_log": console_log,
                "run_time": modified.isoformat(timespec="seconds"),
                "model": answer.get("_model"),
            }
        )
    return rows


def main() -> None:
    rows = build_rows()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {OUT} ({len(rows)} rows)")
    for row in rows:
        answer = row["answer_json"]
        print(f"{row['clip_id']}\t{row['question']}\t{answer.get('decision')}")


if __name__ == "__main__":
    main()
