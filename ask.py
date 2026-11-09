"""EvidenceLens POC - online stage (condition B).

question + evidence.json -> Gemini -> validator -> cited answer or abstention

Usage:
    export GEMINI_API_KEY=...
    python ask.py office_door_03 "Was an object left unattended?"
    python ask.py office_door_03 "Why did he leave it?"          # expect abstention
    python ask.py office_door_03 "..." --dry-run                 # print the prompt only

The LLM never sees the video and never computes a timestamp. It may only copy
t_start / t_end of evidence items it cites. The validator rejects anything else.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MODEL_ID = os.environ.get("EVIDENCELENS_MODEL") or "gemini-3.8-flash"
TIME_TOLERANCE_S = 0.5

SYSTEM_RULES = """You are an evidence-grounded CCTV investigation assistant.

Rules you must follow:
1. Answer ONLY from the evidence package given below. Never use outside knowledge
   and never describe anything that is not in the evidence.
2. Every claim must cite at least one evidence ID: an event id (EV-xxxx) or a
   track id (TRK-n) that appears in the evidence.
3. You may only copy t_start / t_end values of the items you cite. Never compute,
   round or invent a time.
4. If the evidence cannot answer the question, set decision to "cannot_determine",
   abstained to true and reason to "insufficient_evidence". Intent, motive,
   identity, emotion, injury and medical state are never observable: abstain.
5. Answer "no" with reason "verified_negative" ONLY if negative_eligible is true
   for the relevant rule; otherwise abstain with "insufficient_evidence". A
   negative claim must cite the coverage ID COV-<rule> (for example
   COV-unattended_object), not a track or an event. If the question limits the
   time (for example "before 00:10", "after 00:20", "between 00:20 and 00:26"),
   set the claim's cited_time_range to exactly that window in seconds. Answer
   "no" only if the window lies fully inside the rule's coverage range and no
   event of that rule overlaps the window. If a confirmed event of that rule
   overlaps the window, answer "yes" citing that event. If only an event that
   is not confirmed overlaps the window, or the window is not fully inside the
   coverage range, abstain with "insufficient_evidence". If the question has no
   time limit, use the full coverage range and answer "no" only if the rule
   found no event at all.
6. Never identify a person, infer guilt or call anything proof.
7. An event with status needs_review is not a confirmation. If the only matching
   events are needs_review, abstain with insufficient_evidence and say the owner
   association is uncertain.

Answer style:
- For a "no" decision (verified_negative), the claim must say what the rule found,
  not what happened in the world. Use the form "The <rule> rule found no <event type>
  over the full clip (<rule definition from the cited thresholds>)" for a question
  about the whole clip, or "The <rule> rule found no <event type> between <start> s
  and <end> s (<rule definition from the cited thresholds>)" for a time-limited
  question. Never say an event "did not occur", "did not happen" or that "nobody entered".
- For a "yes" decision, the claim may only restate what the cited event records
  (event type, track, zone, time range). Do not add detail that is not in the evidence.

Return ONLY a JSON object of this shape:
{
  "decision": "yes" | "no" | "cannot_determine",
  "abstained": true | false,
  "reason": "positive_evidence" | "verified_negative" | "insufficient_evidence",
  "claims": [
    {
      "text": "<one plain sentence>",
      "cited_ids": ["EV-0001", "TRK-7"],
      "cited_time_range": [<t_start>, <t_end>]
    }
  ],
  "human_review_required": true
}
An abstention has an empty claims list."""


# ---------------------------------------------------------------- validator

def _real_number(value) -> bool:
    """int or float. bool is a subclass of int and is not a timestamp."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(answer: dict, evidence: dict) -> tuple[bool, list[str]]:
    """Schema, ID existence and timestamp check. Returns (ok, list of problems)."""
    if not isinstance(answer, dict):
        return False, ["reply must be a JSON object"]

    problems: list[str] = []

    for key in ("decision", "abstained", "reason", "claims", "human_review_required"):
        if key not in answer:
            problems.append(f"missing field: {key}")
    if problems:
        return False, problems

    if answer["decision"] not in {"yes", "no", "cannot_determine"}:
        problems.append(f"bad decision value: {answer['decision']!r}")
    if answer["decision"] == "cannot_determine" and answer["abstained"] is not True:
        problems.append("cannot_determine requires abstained true")
    if answer["abstained"] is True and answer["decision"] != "cannot_determine":
        problems.append("abstained true requires decision cannot_determine")
    if answer["reason"] not in {"positive_evidence", "verified_negative", "insufficient_evidence"}:
        problems.append(f"bad reason value: {answer['reason']!r}")
    if answer["human_review_required"] is not True:
        problems.append("human_review_required must be true")

    # index every citable id and its time span
    spans: dict[str, tuple[float, float]] = {}
    for ev in evidence.get("events", []):
        spans[ev["event_id"]] = (ev["t_start"], ev["t_end"])
    for tr in evidence.get("tracks", []):
        spans[tr["track_id"]] = (tr["t_start"], tr["t_end"])
    for rule, ranges in (evidence.get("coverage") or {}).items():
        if not ranges:
            continue
        spans[f"COV-{rule}"] = (
            min(float(span[0]) for span in ranges),
            max(float(span[1]) for span in ranges),
        )

    claims = answer.get("claims") or []
    if answer["abstained"] and claims:
        problems.append("abstained answers must have no claims")
    if not answer["abstained"] and not claims:
        problems.append("a non-abstained answer must have at least one claim")

    for i, claim in enumerate(claims):
        cited = claim.get("cited_ids") or []
        if not cited:
            problems.append(f"claim {i}: no cited_ids")
            continue
        unknown = [cid for cid in cited if cid not in spans]
        if unknown:
            problems.append(f"claim {i}: unknown id(s) {unknown}")
            continue

        rng = claim.get("cited_time_range")
        if rng is None:
            continue
        if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
            problems.append(f"claim {i}: cited_time_range must be [start, end]")
            continue
        if not (_real_number(rng[0]) and _real_number(rng[1])):
            problems.append(f"claim {i}: cited_time_range values must be numbers")
            continue
        if float(rng[0]) > float(rng[1]):
            problems.append(
                f"claim {i}: cited_time_range start {rng[0]} is after end {rng[1]}"
            )
        lo = min(spans[c][0] for c in cited) - TIME_TOLERANCE_S
        hi = max(spans[c][1] for c in cited) + TIME_TOLERANCE_S
        if not (lo <= float(rng[0]) <= hi and lo <= float(rng[1]) <= hi):
            problems.append(
                f"claim {i}: time range {rng} outside the cited spans "
                f"[{lo + TIME_TOLERANCE_S:.1f}, {hi - TIME_TOLERANCE_S:.1f}] (+/-{TIME_TOLERANCE_S}s)"
            )

    if answer["reason"] == "verified_negative":
        cov_ids = [
            cid for claim in claims
            for cid in (claim.get("cited_ids") or [])
            if str(cid).startswith("COV-")
        ]
        if not cov_ids:
            problems.append("verified_negative must cite a COV-<rule> id, not a track or an event")
        eligible = evidence.get("negative_eligible") or {}
        for cid in cov_ids:
            rule = str(cid)[4:]
            if eligible.get(rule) is not True:
                problems.append(f"verified_negative is not eligible for {rule}")
        coverage = evidence.get("coverage") or {}
        for claim in claims:
            claim_cov = [
                str(cid) for cid in (claim.get("cited_ids") or [])
                if str(cid).startswith("COV-")
            ]
            if not claim_cov:
                continue
            rng = claim.get("cited_time_range")
            stated = None
            if (
                isinstance(rng, (list, tuple))
                and len(rng) == 2
                and _real_number(rng[0])
                and _real_number(rng[1])
            ):
                stated = (float(rng[0]), float(rng[1]))
            elif rng is not None:
                continue
            for cid in claim_cov:
                rule = cid[4:]
                ranges = coverage.get(rule) or []
                if not ranges:
                    continue
                cov_lo = min(float(span[0]) for span in ranges)
                cov_hi = max(float(span[1]) for span in ranges)
                window = stated if stated is not None else (cov_lo, cov_hi)
                if window[0] < cov_lo or window[1] > cov_hi:
                    problems.append(
                        f"verified_negative range [{window[0]}, {window[1]}] "
                        f"is outside COV-{rule} coverage [{cov_lo}, {cov_hi}]"
                    )
                for ev in evidence.get("events") or []:
                    if ev.get("type") != rule:
                        continue
                    if "t_start" not in ev or "t_end" not in ev:
                        continue
                    ev_start = float(ev["t_start"])
                    ev_end = float(ev["t_end"])
                    if ev_start < window[1] and ev_end > window[0]:
                        problems.append(
                            f"verified_negative range overlaps {ev.get('event_id')}"
                        )

    if answer["reason"] == "positive_evidence":
        events_by_id = {ev["event_id"]: ev for ev in evidence.get("events", [])}
        cited = [
            cid for claim in claims
            for cid in (claim.get("cited_ids") or [])
        ]
        confirmed = [
            cid for cid in cited
            if str(cid).startswith("EV-")
            and events_by_id.get(cid, {}).get("status") == "confirmed_by_rule"
        ]
        if not confirmed:
            problems.append(
                "positive_evidence must cite an event with status confirmed_by_rule"
            )
    return (not problems), problems


def abstention(note: str) -> dict:
    return {
        "decision": "cannot_determine",
        "abstained": True,
        "reason": "insufficient_evidence",
        "claims": [],
        "human_review_required": True,
        "_note": note,
    }


# ---------------------------------------------------------------- prompt and LLM

def build_prompt(question: str, evidence: dict, retry_note: str | None = None) -> str:
    """Condition B input: the evidence package as JSON, nothing else."""
    slim = {
        "video": {k: evidence["video"][k] for k in ("video_id", "duration_s", "fps_native")},
        "zones": evidence.get("zones", []),
        "tracks": evidence.get("tracks", []),
        "events": [{k: v for k, v in ev.items() if k != "supporting_frames"}
                   for ev in evidence.get("events", [])],
        "coverage": evidence.get("coverage", {}),
        "negative_eligible": evidence.get("negative_eligible", {}),
        "detector_summary": evidence.get("detector_summary", {}),
        "limits": evidence.get("limits", []),
    }
    parts = [
        SYSTEM_RULES,
        "\n--- EVIDENCE PACKAGE ---\n" + json.dumps(slim, indent=2),
        "\n--- QUESTION ---\n" + question,
    ]
    if retry_note:
        parts.append(
            "\n--- YOUR PREVIOUS ANSWER WAS REJECTED ---\n" + retry_note +
            "\nReturn a corrected JSON object. If you cannot cite valid evidence, abstain."
        )
    return "\n".join(parts)


_FATAL_HTTP = {400, 401, 403, 404}
_TRANSIENT_HTTP = {429, 500, 503, 504}
_API_RETRY_WAITS_S = (5, 15, 45)


def _status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    return "timeout" in type(exc).__name__.lower()


def classify_api_error(exc: BaseException) -> str:
    """fatal: stop. transient: retry. bad_output: the model repair loop."""
    if isinstance(exc, json.JSONDecodeError):
        return "bad_output"
    if isinstance(exc, ValueError) and "json" in str(exc).lower():
        return "bad_output"
    status = _status_code(exc)
    if status in _FATAL_HTTP:
        return "fatal"
    if status in _TRANSIENT_HTTP or _is_timeout(exc):
        return "transient"
    return "fatal"


def _public_error(exc: BaseException) -> str:
    text = str(exc)
    key = os.environ.get("GEMINI_API_KEY") or ""
    if key and key in text:
        text = text.replace(key, "<REDACTED>")
    return text


def _token_counts(resp: object) -> dict:
    """Input, output and total tokens from a Gemini response. Missing counts stay null."""
    usage = getattr(resp, "usage_metadata", None)

    def one(name: str):
        value = getattr(usage, name, None) if usage is not None else None
        return value if isinstance(value, int) else None

    return {
        "input": one("prompt_token_count"),
        "output": one("candidates_token_count"),
        "total": one("total_token_count"),
    }


def _merge_token_counts(total: dict, part: dict) -> None:
    for key in ("input", "output", "total"):
        value = part.get(key)
        if not isinstance(value, int):
            continue
        total[key] = value if total.get(key) is None else total[key] + value


def call_gemini(prompt: str) -> tuple[dict, dict]:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("set GEMINI_API_KEY in your environment")
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config={"temperature": 0, "response_mime_type": "application/json"},
    )
    counts = _token_counts(resp)
    text = (resp.text or "").strip()
    try:
        return json.loads(text), counts
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError(f"model did not return JSON: {text[:200]}")
        return json.loads(match.group(0)), counts


# ---------------------------------------------------------------- main

def ask(clip_id: str, question: str, evidence_root: Path, dry_run: bool) -> dict:
    evidence_path = evidence_root / clip_id / "evidence.json"
    if not evidence_path.exists():
        raise SystemExit(f"no evidence package at {evidence_path} - run build_evidence.py first")
    evidence = json.loads(evidence_path.read_text())

    prompt = build_prompt(question, evidence)
    if dry_run:
        print(prompt)
        return {}

    api_errors: list[str] = []
    api_retries = 0
    token_counts = {"input": None, "output": None, "total": None}

    def call_model(text: str) -> tuple[str, dict | str]:
        """Return ('ok', parsed), ('bad_output', message), ('fatal', message) or ('give_up', message)."""
        nonlocal api_retries
        transient_retries = 0
        while True:
            try:
                parsed, counts = call_gemini(text)
                _merge_token_counts(token_counts, counts)
                return "ok", parsed
            except Exception as exc:
                kind = classify_api_error(exc)
                message = _public_error(exc)
                if kind == "bad_output":
                    return "bad_output", message
                print(message)
                api_errors.append(message)
                if kind == "fatal" or transient_retries >= len(_API_RETRY_WAITS_S):
                    return ("fatal" if kind == "fatal" else "give_up"), message
                time.sleep(_API_RETRY_WAITS_S[transient_retries])
                transient_retries += 1
                api_retries += 1

    def api_error_result(attempts: int) -> dict:
        return {
            "decision": None,
            "abstained": False,
            "reason": None,
            "status": "api_error",
            "claims": [],
            "human_review_required": True,
            "_api_errors": list(api_errors),
            "_api_retries": api_retries,
            "_attempts": attempts,
            "_latency_ms": round((time.perf_counter() - t0) * 1000),
            "_token_counts": dict(token_counts),
            "_validated": False,
            "_clip_id": clip_id,
            "_condition": "B",
            "_model": MODEL_ID,
        }

    def finish(answer: dict, attempts: int, validated: bool) -> dict:
        answer["_latency_ms"] = round((time.perf_counter() - t0) * 1000)
        answer["_attempts"] = attempts
        answer["_api_retries"] = api_retries
        answer["_api_errors"] = list(api_errors)
        answer["_token_counts"] = dict(token_counts)
        answer["_validated"] = validated
        answer["_clip_id"] = clip_id
        answer["_condition"] = "B"
        answer["_model"] = MODEL_ID
        return answer

    t0 = time.perf_counter()
    kind, payload = call_model(prompt)
    if kind in ("fatal", "give_up"):
        return api_error_result(0)

    attempts = 1
    if kind == "ok":
        answer = payload
        ok, problems = validate(answer, evidence)
    else:
        answer = None
        ok, problems = False, [payload]

    if not ok:
        print(f"  validator rejected attempt 1: {problems}")
        attempts = 2
        kind, payload = call_model(build_prompt(question, evidence, retry_note="; ".join(problems)))
        if kind in ("fatal", "give_up"):
            return api_error_result(attempts)
        if kind == "bad_output":
            print(f"  validator rejected attempt 2: {[payload]}")
            answer = abstention("validator rejected the model output twice")
            ok = True
        else:
            answer = payload
            ok, problems = validate(answer, evidence)
            if not ok:
                print(f"  validator rejected attempt 2: {problems}")
                answer = abstention("validator rejected the model output twice")
                ok = True

    return finish(answer, attempts, ok)


def render(answer: dict, evidence_root: Path) -> None:
    print("\n" + "=" * 60)
    if answer.get("status") == "api_error":
        print("status: api_error   decision: null   abstained: false")
        for message in answer.get("_api_errors") or []:
            print(message)
        print("-" * 60)
        print("API ERROR. NOT AN ABSTENTION. NOT PROOF.")
        print(f"{answer['_latency_ms']} ms, {answer['_api_retries']} API retry(ies), "
              f"{answer['_attempts']} repair attempt(s)")
        print("=" * 60)
        return
    print(f"decision: {answer['decision']}   abstained: {answer['abstained']}   "
          f"reason: {answer['reason']}")
    print("-" * 60)
    if not answer["claims"]:
        print("  (no claims - cannot determine from evidence)")
    frames_dir = evidence_root / answer["_clip_id"] / "frames"
    for claim in answer["claims"]:
        print(f"  {claim['text']}")
        rng = claim.get("cited_time_range")
        print(f"    cites: {', '.join(claim['cited_ids'])}"
              + (f"   time: {rng[0]}s to {rng[1]}s" if rng else ""))
        for cid in claim["cited_ids"]:
            if cid.startswith("EV-"):
                hits = sorted(frames_dir.glob(f"{cid}_*.jpg"))
                if hits:
                    print(f"    frames: {', '.join(p.name for p in hits)}")
    print("-" * 60)
    print("FOR HUMAN REVIEW. NOT PROOF.")
    print(f"{answer['_latency_ms']} ms, {answer['_attempts']} LLM call(s), "
          f"validated: {answer['_validated']}")
    print("=" * 60)


def main() -> None:
    ap = argparse.ArgumentParser(description="EvidenceLens POC - ask a question (condition B)")
    ap.add_argument("clip_id", help="the clip stem, e.g. office_door_03")
    ap.add_argument("question")
    ap.add_argument("--evidence-root", default="data/evidence")
    ap.add_argument("--dry-run", action="store_true", help="print the prompt, call nothing")
    ap.add_argument("--json", action="store_true", help="print the raw answer JSON")
    args = ap.parse_args()

    root = Path(args.evidence_root)
    answer = ask(args.clip_id, args.question, root, args.dry_run)
    if not answer:
        return
    if args.json:
        print(json.dumps(answer, indent=2))
    else:
        render(answer, root)


if __name__ == "__main__":
    main()
