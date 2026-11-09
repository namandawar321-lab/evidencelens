"""EvidenceLens demo.

Four screens: Clip library, Investigate, Incident report, Analyse a new clip.
Ask uses the answer cache. Replay shows saved runs. This file does not
detect events, edit rules, or read .env.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
import streamlit.components.v1 as components

from ask import TIME_TOLERANCE_S, validate
from build_evidence import THRESHOLDS
from clip_media import annotated_path, ensure_annotated, ensure_event_clip
from live_monitor import AUTO_STOP_TEXT, clear_stop_flag, request_stop, stop_flag_path
from llm_cache import ask_cached, lookup_cached
from ui.eval_summary import footer_text
from make_saved_answers import QUESTION_BY_SUFFIX
from record_clip import (
    consent_refusal,
    licence_log_row,
    rejection_reason,
)
ROOT = Path(__file__).resolve().parent
EVIDENCE_ROOT = ROOT / "data" / "evidence"
CLIPS_ROOT = ROOT / "data" / "clips"
MANIFEST_PATH = ROOT / "data" / "saved_answers" / "manifest.json"
CLIP_META_PATH = ROOT / "data" / "clips_meta.json"
ZONES_ROOT = ROOT / "data" / "zones"
LICENCE_LOG = ROOT / "licence_log.csv"
LOCAL_ZONE = ZoneInfo("Asia/Calcutta")
REVIEW_LOG = ROOT / "data" / "review_log.jsonl"
ANALYSE_LABEL = "Record, then analyse. This is not real-time streaming."
LIVE_LABEL = (
    "Live preview is provisional. Evidence and answers come from the recorded session. "
    "The language model is not in the live loop."
)
CONSENT_BASIS = "people in this clip have consented / I own this clip"

SAMPLE_QUESTIONS = list(QUESTION_BY_SUFFIX.values())
ZONE_QUESTIONS = (
    "Did anyone enter the restricted zone?",
    "Did anyone enter the zone before 00:10?",
)
BAG_QUESTION = "Was an object left unattended?"
FALL_NOTE = (
    "Falls are not checked. EvidenceLens has no fall rule yet, so it cannot "
    "say whether anyone fell."
)
SCREENS = ["Clip library", "Investigate", "Incident report", "Analyse a new clip"]
PAGES = (
    ("home", "Home", "Home"),
    ("library", "Library", "Clip library"),
    ("investigate", "Investigate", "Investigate"),
    ("report", "Report", "Incident report"),
    ("analyse", "Analyse", "Analyse a new clip"),
)
PAGE_OF = {}
for _pid, _label, _old in PAGES:
    PAGE_OF[_pid] = _pid
    PAGE_OF[_label] = _pid
    PAGE_OF[_old] = _pid
SCREEN_OF = {pid: old for pid, _label, old in PAGES}
REVIEW_CHIP = "For human review · not proof"
RULES = ("unattended_object", "zone_intrusion", "fall")
CAVIAR_NOTE = (
    "Data from the EC Funded CAVIAR project/IST 2001 37540, "
    "http://homepages.inf.ed.ac.uk/rbf/CAVIAR/ (CC BY-SA)"
)
LIMITS_LINE = (
    "single camera; no identification of people; rule thresholds are design assumptions"
)
COV_SENTENCE = (
    "the rule checked this time range; this is not proof that nothing happened"
)
AMBER = "For human review. Not proof."

st.set_page_config(
    page_title="EvidenceLens",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def inject_css() -> None:
    """One stylesheet, built from the tokens in ui.theme."""
    import importlib
    import ui.theme as theme_mod

    importlib.reload(theme_mod)
    st.markdown(theme_mod.GLOBAL_CSS, unsafe_allow_html=True)


def banner_html(css_class: str, text: str) -> None:
    st.markdown(
        f"<div class='{css_class}'>{html.escape(text)}</div>",
        unsafe_allow_html=True,
    )


def public_text(text: str) -> str:
    """Drop a loaded API key if it ever appears in a message. Never display it."""
    key = os.environ.get("GEMINI_API_KEY") or ""
    if key and key in text:
        return text.replace(key, "[redacted]")
    return text


def format_time(seconds) -> str:
    """mm:ss.s, for example 00:18.2."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "00:00.0"
    sign = "-" if value < 0 else ""
    value = abs(value)
    minutes = int(value // 60)
    remain = value - minutes * 60
    return f"{sign}{minutes:02d}:{remain:04.1f}"


def format_span(start, end) -> str:
    return f"{format_time(start)}–{format_time(end)}"


def short_stamp(value: str | None) -> str:
    """Local time in Asia/Calcutta, for example 30 Oct 06:50."""
    text = str(value or "").strip()
    if not text or text == "time not recorded":
        return "time not recorded"
    stamp = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return "time not recorded"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    local = parsed.astimezone(LOCAL_ZONE)
    return f"{local.day} {local.strftime('%b %H:%M')}"


def load_manifest() -> list[dict]:
    if not MANIFEST_PATH.is_file():
        return []
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def clip_questions(clip_id: str, evidence: dict | None) -> list[str]:
    """Chips for this clip. A missing package lists every question, shown disabled."""
    if evidence is None:
        return [*ZONE_QUESTIONS, BAG_QUESTION]
    questions: list[str] = []
    zones = evidence.get("zones") or []
    zone_coverage = (evidence.get("coverage") or {}).get("zone_intrusion") or []
    bag_tracks = (evidence.get("detector_summary") or {}).get("bag_tracks") or 0
    if zones or zone_coverage:
        questions.extend(ZONE_QUESTIONS)
    if bag_tracks or "bag" in clip_id.lower():
        questions.append(BAG_QUESTION)
    return questions


def clip_ids() -> list[str]:
    if not EVIDENCE_ROOT.is_dir():
        return []
    found = []
    for path in sorted(EVIDENCE_ROOT.iterdir()):
        if path.is_dir() and (path / "evidence.json").is_file():
            found.append(path.name)
    return found


def load_evidence(clip_id: str) -> dict:
    path = EVIDENCE_ROOT / clip_id / "evidence.json"
    return json.loads(path.read_text(encoding="utf-8"))


def find_saved(manifest: list[dict], clip_id: str, question: str) -> dict | None:
    for row in manifest:
        if row.get("clip_id") == clip_id and row.get("question") == question:
            return row
    return None


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


def events_for_rule(evidence: dict, rule: str) -> list[dict]:
    return [ev for ev in evidence.get("events") or [] if ev.get("type") == rule or ev.get("rule_id") == rule]


def rule_gap_row(evidence: dict, rule: str) -> dict:
    duration = float((evidence.get("video") or {}).get("duration_s") or 0)
    ranges = (evidence.get("coverage") or {}).get(rule) or []
    eligible = (evidence.get("negative_eligible") or {}).get(rule) is True
    base = {"Event": "none", "Type": rule, "Time": "", "Conf.": "", "Status": "", "Zone": "", "Dwell": ""}
    if not ranges:
        base["Type"] = f"{rule} (rule did not run)"
        base["Time"] = "not run"
        base["Status"] = "rule did not run"
        return base
    if not coverage_spans_clip(ranges, duration):
        base["Type"] = f"{rule} (coverage partial)"
        base["Time"] = "coverage partial"
        base["Status"] = "coverage incomplete"
        return base
    if not eligible:
        base["Type"] = f"{rule} (rule ran)"
        base["Time"] = "full clip covered"
        base["Status"] = "cannot verify, no relevant object was detected"
        return base
    base["Type"] = f"{rule} (rule ran)"
    base["Time"] = "full clip covered"
    base["Status"] = "verified_negative"
    return base


def show_value(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def canonical_page(value: str) -> str:
    return PAGE_OF.get(value, "investigate")


def apply_navigation() -> None:
    """Restore page, clip, question, and view from the URL. Buttons never reload the app."""
    if "page" not in st.session_state:
        raw = str(st.query_params.get("page") or st.query_params.get("screen") or "")
        st.session_state.page = canonical_page(raw) if raw else "investigate"
    if "ui_view" not in st.session_state:
        view = str(st.query_params.get("view") or "simple")
        st.session_state.ui_view = view if view in ("simple", "technical") else "simple"
    saved_clip = str(st.query_params.get("clip") or "")
    if saved_clip and "clip_id" not in st.session_state and saved_clip in clip_ids():
        st.session_state.clip_id = saved_clip
    saved_question = st.query_params.get("q")
    if saved_question and "question" not in st.session_state:
        st.session_state.question = str(saved_question)
    if "nav_screen" in st.session_state:
        st.session_state.page = canonical_page(str(st.session_state.pop("nav_screen")))
    if "nav_clip" in st.session_state:
        st.session_state.clip_id = st.session_state.pop("nav_clip")
    if "pending_question" in st.session_state:
        st.session_state.question = st.session_state.pop("pending_question")
    if "question" not in st.session_state:
        st.session_state.question = SAMPLE_QUESTIONS[0]
    if "answer_view" not in st.session_state:
        st.session_state.answer_view = "Ask"
    st.session_state.screen = SCREEN_OF.get(st.session_state.page, "Investigate")
    seen = st.session_state.get("clip_q_seen")
    current = (st.session_state.get("clip_id"), st.session_state.get("question"))
    if seen is not None and seen != current:
        st.session_state.selected_ref = None
        st.session_state.pop("watch_start", None)
    st.session_state.clip_q_seen = current


def append_review(clip_id: str, question: str, claim_index: int, verdict: str) -> None:
    REVIEW_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "clip_id": clip_id,
        "question": question,
        "claim_index": claim_index,
        "verdict": verdict,
    }
    with REVIEW_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line) + "\n")


def cited_pairs(answer: dict) -> list[tuple[int, dict]]:
    pairs = []
    for index, claim in enumerate(answer.get("claims") or []):
        if isinstance(claim, dict):
            pairs.append((index, claim))
    return pairs


def evidence_index(evidence: dict) -> dict[str, tuple[float, float]]:
    spans: dict[str, tuple[float, float]] = {}
    for event in evidence.get("events") or []:
        spans[event["event_id"]] = (float(event["t_start"]), float(event["t_end"]))
    for track in evidence.get("tracks") or []:
        spans[track["track_id"]] = (float(track["t_start"]), float(track["t_end"]))
    for rule, ranges in (evidence.get("coverage") or {}).items():
        if not ranges:
            continue
        spans[f"COV-{rule}"] = (
            min(float(span[0]) for span in ranges),
            max(float(span[1]) for span in ranges),
        )
    return spans


def check_lines(answer: dict, evidence: dict, source_text: str) -> list[tuple[str, str]]:
    """Text labels for how the answer was checked. Colour is not the only signal."""
    if answer.get("status") == "api_error":
        return [
            ("note", "schema valid: not checked, this is an API error"),
            ("note", "cited IDs exist: not checked, this is an API error"),
            ("note", "cited times within spans: not checked, this is an API error"),
            ("note", "yes backed by a confirmed event: not checked, this is an API error"),
            ("note", f"source: {source_text}"),
        ]
    spans = evidence_index(evidence)
    schema = []
    for key in ("decision", "abstained", "reason", "claims", "human_review_required"):
        if key not in answer:
            schema.append(key)
    if not schema and answer.get("decision") not in {"yes", "no", "cannot_determine"}:
        schema.append("decision")
    if not schema and answer.get("reason") not in {"positive_evidence", "verified_negative", "insufficient_evidence"}:
        schema.append("reason")
    if not schema and answer.get("human_review_required") is not True:
        schema.append("human_review_required")
    missing_ids = []
    time_bad = False
    for _index, claim in cited_pairs(answer):
        for cid in claim.get("cited_ids") or []:
            if cid not in spans:
                missing_ids.append(str(cid))
        rng = claim.get("cited_time_range")
        cited = [cid for cid in (claim.get("cited_ids") or []) if cid in spans]
        if rng is None or not cited:
            continue
        if not (isinstance(rng, (list, tuple)) and len(rng) == 2):
            time_bad = True
            continue
        lo = min(spans[cid][0] for cid in cited) - TIME_TOLERANCE_S
        hi = max(spans[cid][1] for cid in cited) + TIME_TOLERANCE_S
        if not (lo <= float(rng[0]) <= hi and lo <= float(rng[1]) <= hi):
            time_bad = True
    events_by_id = {event["event_id"]: event for event in evidence.get("events") or []}
    cited_ids = [cid for _i, claim in cited_pairs(answer) for cid in (claim.get("cited_ids") or [])]
    confirmed = [
        cid for cid in cited_ids
        if str(cid).startswith("EV-") and events_by_id.get(cid, {}).get("status") == "confirmed_by_rule"
    ]
    yes_answer = answer.get("reason") == "positive_evidence" or answer.get("decision") == "yes"
    if not yes_answer:
        yes_line = ("note", "yes backed by a confirmed event: not a yes answer")
    elif confirmed:
        yes_line = ("pass", "pass: yes is backed by a confirmed_by_rule event")
    else:
        yes_line = ("fail", "fail: yes is not backed by a confirmed_by_rule event")
    try:
        ok, problems = validate(answer, evidence)
    except Exception as exc:
        ok, problems = False, [public_text(f"validator raised {type(exc).__name__}")]
    lines = [
        ("pass" if not schema else "fail", "pass: schema valid" if not schema else "fail: schema invalid (" + ", ".join(schema) + ")"),
        ("pass" if not missing_ids else "fail", "pass: cited IDs exist" if not missing_ids else "fail: unknown id " + ", ".join(missing_ids)),
        ("pass" if not time_bad else "fail", "pass: cited times within spans" if not time_bad else "fail: a cited time is outside its span"),
        yes_line,
        ("note", f"source: {source_text}"),
        ("pass" if ok else "fail", "pass: validator accepted this answer" if ok else "fail: validator rejected this answer"),
    ]
    if not ok:
        for item in problems:
            lines.append(("fail", "fail: " + public_text(str(item))))
    return lines


def focus_first_cited(answer: dict) -> None:
    """Open the evidence panel on the first cited ID, including a COV- id."""
    cited = []
    for _index, claim in cited_pairs(answer):
        cited.extend(str(cid) for cid in (claim.get("cited_ids") or []))
    current = st.session_state.get("selected_ref")
    if not cited:
        if current:
            st.session_state.selected_ref = None
        return
    if current not in cited:
        st.session_state.selected_ref = cited[0]


def rule_for_question(question: str) -> str:
    text = question.lower()
    if "fall" in text:
        return "fall"
    if any(word in text for word in ("unattended", "bag", "suitcase", "object", "left")):
        return "unattended_object"
    if any(word in text for word in ("zone", "restricted", "enter")):
        return "zone_intrusion"
    return "unattended_object"


def thresholds_for(evidence: dict, rule: str) -> dict:
    found: dict = {}
    for event in evidence.get("events") or []:
        if event.get("type") == rule or event.get("rule_id") == rule:
            found.update(event.get("thresholds") or {})
    return found


def rule_definition(evidence: dict, rule: str) -> str:
    """Plain description from thresholds stored on the evidence, not from the model."""
    recorded = thresholds_for(evidence, rule)
    if rule == "zone_intrusion":
        dwell = recorded.get("dwell_min_s")
        if dwell is None:
            dwell = THRESHOLDS["intrusion_dwell_s"]
        return f"foot point inside the zone for at least {float(dwell):.1f} s"
    if rule == "unattended_object":
        away = recorded.get("T_s")
        if away is None:
            away = THRESHOLDS["unattended_T_s_short"]
        return f"the bag stays still and the owner stays away for at least {float(away):.0f} s"
    if rule == "fall":
        return "the fall rule is not implemented"
    conf = recorded.get("conf_min")
    if conf is None:
        conf = (evidence.get("provenance") or {}).get("conf_threshold")
    if conf is not None:
        return f"detection confidence at least {conf}"
    return "the thresholds recorded for this rule"


def cited_rule(answer: dict, evidence: dict, question: str) -> str:
    for _index, claim in cited_pairs(answer):
        for cid in claim.get("cited_ids") or []:
            if str(cid).startswith("COV-"):
                return str(cid)[4:]
    for event in evidence.get("events") or []:
        if event.get("rule_id"):
            return str(event["rule_id"])
    return rule_for_question(question)


def no_caveat(answer: dict, evidence: dict, question: str) -> str | None:
    if answer.get("decision") != "no" and answer.get("reason") != "verified_negative":
        return None
    rule = cited_rule(answer, evidence, question)
    return (
        f"A 'no' means the {rule} rule found nothing over the full clip "
        f"({rule_definition(evidence, rule)}). "
        "It does not rule out brief or partial events the rule cannot see."
    )


def abstention_plain(evidence: dict, question: str) -> str:
    """A reason built from coverage and detector counts, not from the model."""
    rule = rule_for_question(question)
    duration = float((evidence.get("video") or {}).get("duration_s") or 0)
    ranges = (evidence.get("coverage") or {}).get(rule) or []
    summary = evidence.get("detector_summary") or {}
    full = coverage_spans_clip(ranges, duration)
    if rule == "unattended_object":
        bags = int(summary.get("bag_tracks") or 0)
        if not ranges:
            return (
                "The unattended_object rule did not run on this clip, "
                "so an abandoned object cannot be determined from the evidence."
            )
        if not full:
            return (
                "The unattended_object rule did not cover the whole clip, "
                "so an abandoned object cannot be determined from the evidence."
            )
        if bags == 0:
            return (
                "The unattended_object rule ran over the full clip, but no bag or suitcase "
                "was detected, so the absence of an abandoned object cannot be verified."
            )
        return (
            "The unattended_object rule ran over the full clip, but the evidence is not "
            "enough to decide whether an object was left unattended."
        )
    if rule == "zone_intrusion":
        people = int(summary.get("person_tracks") or 0)
        if not ranges:
            return "The zone_intrusion rule did not run on this clip, so an entry cannot be determined from the evidence."
        if not full:
            return "The zone_intrusion rule did not cover the whole clip, so an entry cannot be determined from the evidence."
        if people == 0:
            return (
                "The zone_intrusion rule ran over the full clip, but no person was detected, "
                "so the absence of an entry cannot be verified."
            )
        return (
            "The zone_intrusion rule ran over the full clip, but the evidence is not "
            "enough to decide whether anyone entered the zone."
        )
    if not ranges:
        return "The fall rule did not run, so a fall cannot be determined from the evidence."
    return "The fall rule did not produce a decision, so a fall cannot be determined from the evidence."


def source_text_for(kind: str, when: str | None = None) -> str:
    if kind == "cached":
        return f"cached ({when})" if when else "cached"
    if kind == "replay":
        return f"replay ({when})" if when else "replay"
    return "live"


def render_checks(lines: list[tuple[str, str]]) -> None:
    body = []
    for index, (kind, text) in enumerate(lines):
        css = {"pass": "el-pass-line", "fail": "el-fail-line"}.get(kind, "el-note-line")
        delay = index * 80
        body.append(
            f"<p class='{css} el-tick-in' style='animation-delay:{delay}ms'>{html.escape(text)}</p>"
        )
    st.markdown(
        "<div class='el-checks'><p class='el-label'>How this answer was checked</p>"
        + "".join(body)
        + "</div>",
        unsafe_allow_html=True,
    )


def render_answer_card(answer: dict, clip_id: str, question: str, key_prefix: str) -> None:
    if answer.get("status") == "api_error":
        banner_html("el-api", "API error. This is not an abstention.")
        for message in answer.get("_api_errors") or []:
            st.text(public_text(str(message)))
        return
    if answer.get("abstained"):
        css = "el-neutral"
    elif answer.get("decision") == "yes":
        css = "el-yes"
    elif answer.get("decision") == "no":
        css = "el-no"
    else:
        css = "el-neutral"
    line = (
        f"decision: {show_value(answer.get('decision'))}   "
        f"abstained: {show_value(answer.get('abstained'))}   "
        f"reason: {show_value(answer.get('reason'))}"
    )
    st.markdown(
        f"<div class='el-card {css}'><p class='el-label'>Answer</p><p>{html.escape(line)}</p></div>",
        unsafe_allow_html=True,
    )
    claims = answer.get("claims") or []
    if not claims:
        st.write("claims: none")
        return
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            st.write(str(claim))
            continue
        st.write(claim.get("text") or "")
        cited = [str(cid) for cid in (claim.get("cited_ids") or [])]
        if cited:
            chip_cols = st.columns(len(cited))
            for chip_col, cid in zip(chip_cols, cited):
                with chip_col:
                    if st.button(cid, key=f"{key_prefix}-cite-{clip_id}-{index}-{cid}"):
                        st.session_state.selected_ref = cid
        rng = claim.get("cited_time_range")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            st.write(f"cited time range: {format_time(rng[0])} to {format_time(rng[1])}")


def render_abstention(answer: dict, evidence: dict, question: str) -> None:
    if answer.get("status") == "api_error" or not answer.get("abstained"):
        return
    reason = show_value(answer.get("reason"))
    plain = abstention_plain(evidence, question)
    st.markdown(
        "<div class='el-abstain-dash'><p class='el-label'>Abstention</p>"
        f"<p>Cannot determine from evidence: {html.escape(reason)}</p>"
        f"<p>{html.escape(plain)}</p></div>",
        unsafe_allow_html=True,
    )


def claim_index_for(answer: dict, ref: str) -> int:
    for index, claim in cited_pairs(answer):
        if ref in [str(cid) for cid in (claim.get("cited_ids") or [])]:
            return index
    return 0


def render_verdict(
    clip_id: str,
    question: str,
    claim_index: int,
    key_prefix: str,
    reject_label: str = "Reject",
) -> None:
    verdicts = st.session_state.setdefault("verdicts", {})
    key = f"{key_prefix}|{clip_id}|{question}|{claim_index}"
    confirm_col, reject_col = st.columns(2)
    with confirm_col:
        if st.button("Confirm", key=f"{key_prefix}-confirm-{clip_id}-{claim_index}"):
            verdicts[key] = "Confirmed"
            append_review(clip_id, question, claim_index, "Confirmed")
    with reject_col:
        if st.button(reject_label, key=f"{key_prefix}-reject-{clip_id}-{claim_index}"):
            verdicts[key] = "Rejected"
            append_review(clip_id, question, claim_index, "Rejected")
    if key in verdicts:
        st.write(verdicts[key])


def zone_name(evidence: dict, zone_id: str | None) -> str:
    for zone in evidence.get("zones") or []:
        if zone.get("zone_id") == zone_id:
            return str(zone.get("label") or zone_id)
    return str(zone_id or "")


def moment_labels(event_id: str, rels: list[str]) -> list[tuple[str, str, str]]:
    """Map saved frames onto start / peak / end without repeating a label."""
    slot_of = {"start": "start", "static": "start", "end": "end", "fire": "end", "owner_away": "peak"}
    used: set[str] = set()
    labelled = []
    for rel in rels:
        stem = Path(rel).stem
        suffix = stem.split("_", 1)[1] if "_" in stem else "frame"
        label = slot_of.get(suffix, suffix.replace("_", " "))
        if label in used:
            label = suffix.replace("_", " ")
        if label in used:
            label = f"{label} {len(used) + 1}"
        used.add(label)
        labelled.append((rel, f"{event_id} {label}", suffix))
    return labelled


def moment_time(event: dict, suffix: str) -> str:
    if suffix in {"start", "fire"}:
        return format_time(event.get("t_start"))
    if suffix == "end":
        return format_time(event.get("t_end"))
    if suffix in {"peak", "owner_away"}:
        start = float(event.get("t_start") or 0)
        end = float(event.get("t_end") or 0)
        return f"{format_time((start + end) / 2)} midpoint"
    if suffix == "static":
        return "static frame"
    return format_span(event.get("t_start"), event.get("t_end"))


def frame_at_time(clip_path: Path, t_s: float):
    """One display frame. Nothing is written to the evidence package."""
    import cv2

    if not clip_path.is_file():
        return None
    capture = cv2.VideoCapture(str(clip_path))
    capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(t_s)) * 1000.0)
    ok, frame = capture.read()
    capture.release()
    if not ok or frame is None:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def render_keyframes(clip_id: str, event: dict) -> None:
    event_id = str(event.get("event_id") or "event")
    labelled = moment_labels(event_id, list(event.get("supporting_frames") or []))
    by_caption = {caption: (rel, suffix) for rel, caption, suffix in labelled}
    columns = st.columns(3)
    for column, caption in zip(columns, (f"{event_id} start", f"{event_id} peak", f"{event_id} end")):
        with column:
            found = by_caption.get(caption)
            if found is None and caption.endswith(" peak"):
                start = float(event.get("t_start") or 0)
                end = float(event.get("t_end") or start)
                mid = (start + end) / 2
                frame = frame_at_time(CLIPS_ROOT / f"{clip_id}.mp4", mid)
                label = f"{event_id} peak (extracted for display) · {format_time(mid)}"
                if frame is not None:
                    st.image(frame, caption=label)
                else:
                    st.write(f"{label} — frame could not be read")
                continue
            if found is None:
                st.write(f"{caption}: not in the evidence package")
                continue
            rel, suffix = found
            alt = f"{caption} · {moment_time(event, suffix)}"
            path = EVIDENCE_ROOT / clip_id / rel
            if path.is_file():
                st.image(str(path), caption=alt)
            else:
                st.write(f"{alt} — file missing")


def plain_span_label(event: dict) -> str:
    kind = event.get("type")
    if kind == "zone_intrusion":
        return "Inside the restricted area"
    if kind == "unattended_object":
        return "Bag left behind"
    return str(kind or "Event").replace("_", " ")


def timeline_html(evidence: dict, plain: bool = False, playhead_id: str | None = None) -> str:
    """Event spans on a tint track. A short span keeps its label on its own line."""
    duration = float((evidence.get("video") or {}).get("duration_s") or 0)
    events = list(evidence.get("events") or [])
    if duration <= 0:
        return "<p class='el-tl-label'>No clip duration, so the timeline is empty.</p>"
    if not events:
        rows = [
            "<p class='el-tl-label'>No events on the timeline.</p>",
            "<div class='el-tl-track'>"
            "<i class='el-mark' style='left:0'></i>"
            "<i class='el-mark' style='left:100%'></i>"
            "</div>",
            "<div class='el-tl-times'>"
            "<span class='el-tick' style='left:0'>00:00.0</span>"
            f"<span class='el-tick' style='left:100%;transform:translateX(-100%)'>{html.escape(format_time(duration))}</span>"
            "</div>",
        ]
        return "<div class='el-timeline'>" + "".join(rows) + "</div>"
    blocks = []
    for event in sorted(events, key=lambda item: float(item.get("t_start") or 0)):
        start = float(event.get("t_start") or 0)
        end = float(event.get("t_end") or start)
        left = max(0.0, min(100.0, 100.0 * start / duration))
        right = max(left, min(100.0, 100.0 * end / duration))
        width = max(1.5, right - left)
        label = plain_span_label(event) if plain else f"{event.get('event_id')} {event.get('type')}"
        head = ""
        if playhead_id and event.get("event_id") == playhead_id:
            head = f"<i class='el-playhead' style='left:{left:.2f}%'></i>"
        start_at = min(left, 78.0)
        end_at = right
        if end_at < start_at + 28.0:
            end_at = min(100.0, start_at + 28.0)
        end_style = "left:100%;transform:translateX(-100%)" if end_at >= 99.0 else f"left:{end_at:.2f}%"
        blocks.append(
            "<div class='el-tl-event'>"
            f"<p class='el-tl-label'>{html.escape(label)}</p>"
            "<div class='el-tl-track'>"
            f"<div class='el-span' style='left:{left:.2f}%;width:{width:.2f}%'></div>"
            f"{head}"
            f"<i class='el-mark' style='left:{left:.2f}%'></i>"
            f"<i class='el-mark' style='left:{right:.2f}%'></i>"
            "</div>"
            "<div class='el-tl-times'>"
            f"<span class='el-tick' style='left:{start_at:.2f}%'>{html.escape(format_time(start))}</span>"
            f"<span class='el-tick' style='{end_style}'>{html.escape(format_time(end))}</span>"
            "</div></div>"
        )
    return "<div class='el-timeline'>" + "".join(blocks) + "</div>"


def show_clip_video(
    clip_id: str,
    evidence: dict,
    start_time: float | None = None,
    plain: bool = False,
    playhead_id: str | None = None,
) -> None:
    ready = annotated_path(clip_id)
    note = st.session_state.get(f"annot_note_{clip_id}")
    path = ready if ready.is_file() and ready.stat().st_size > 0 else None
    if path is None and not st.session_state.get(f"annot_fail_{clip_id}"):
        holder = st.empty()
        started = time.perf_counter()
        slot: dict = {}

        def target() -> None:
            try:
                slot["result"] = ensure_annotated(clip_id, evidence)
            except Exception as exc:
                slot["result"] = (None, public_text(f"{type(exc).__name__}: {exc}"))

        worker = threading.Thread(target=target, daemon=True)
        worker.start()
        with st.spinner("Preparing the annotated video…"):
            while worker.is_alive():
                holder.markdown(f"**Preparing the annotated video… {time.perf_counter() - started:.0f} s**")
                time.sleep(0.4)
        worker.join()
        holder.empty()
        path, note = slot.get("result", (None, "The overlay was not written."))
        if path is None:
            st.session_state[f"annot_fail_{clip_id}"] = True
            st.session_state[f"annot_note_{clip_id}"] = note
    plain_file = CLIPS_ROOT / f"{clip_id}.mp4"
    video_kwargs = {}
    if start_time is not None:
        video_kwargs["start_time"] = int(start_time)
    if path is not None and Path(path).is_file():
        st.video(str(path), **video_kwargs)
    elif plain_file.is_file():
        st.video(str(plain_file), **video_kwargs)
        st.write(note or "Showing the plain clip.")
    else:
        st.write(note or "No clip file in data/clips.")
    st.markdown(
        timeline_html(evidence, plain=plain, playhead_id=playhead_id),
        unsafe_allow_html=True,
    )


def render_rule_box(evidence: dict, event: dict, clip_id: str, question: str, answer: dict, key_prefix: str) -> None:
    dwell = float(event.get("t_end") or 0) - float(event.get("t_start") or 0)
    thresholds = event.get("thresholds") or {}
    dwell_min = thresholds.get("dwell_min_s")
    conf_min = thresholds.get("conf_min")
    zone_id = event.get("zone_id")
    name = zone_name(evidence, zone_id) if zone_id else ""
    tracks = ", ".join(str(item) for item in (event.get("track_ids") or [])) or "none"
    rule_col, button_col = st.columns([3, 1])
    with rule_col:
        st.markdown("**Rule**")
        st.write(f"rule id: {event.get('rule_id')} · version: {event.get('rule_version')}")
        if dwell_min is not None:
            st.write(f"dwell: {format_time(dwell)} · threshold: {format_time(dwell_min)}")
        elif thresholds.get("T_s") is not None:
            st.write(f"dwell: {format_time(dwell)} · threshold: {format_time(thresholds.get('T_s'))}")
        else:
            st.write(f"dwell: {format_time(dwell)}")
        st.write(f"confidence threshold: {conf_min if conf_min is not None else 'not recorded'}")
        st.write(f"confidence: {event.get('confidence')}")
        if zone_id:
            st.write(f"zone: {name} ({zone_id})")
        st.write(f"track: {tracks}")
        st.write("rule_trace:")
        st.text(str(event.get("rule_trace") or ""))
    with button_col:
        st.markdown("**Review**")
        render_verdict(clip_id, question, claim_index_for(answer, str(event.get("event_id"))), key_prefix)


def render_event_panel(clip_id: str, evidence: dict, event: dict, answer: dict, question: str, key_prefix: str) -> None:
    event_id = event.get("event_id")
    st.subheader(f"Evidence for {event_id}")
    render_keyframes(clip_id, event)
    st.write(f"Event clip, 3 s before to 3 s after ({format_span(event.get('t_start'), event.get('t_end'))} inside the window)")
    extract, note = ensure_event_clip(clip_id, evidence, event)
    clip_col, _rest = st.columns([3, 2])
    with clip_col:
        if extract is not None:
            st.video(str(extract))
        else:
            plain = CLIPS_ROOT / f"{clip_id}.mp4"
            if plain.is_file():
                duration = (evidence.get("video") or {}).get("duration_s")
                start = max(0.0, float(event.get("t_start") or 0) - 3.0)
                end = float(event.get("t_end") or 0) + 3.0
                if duration is not None:
                    end = min(end, float(duration))
                st.video(str(plain), start_time=start, end_time=end)
            st.write(note or "The +/- 3 s extract is not available.")
    render_rule_box(evidence, event, clip_id, question, answer, key_prefix)


def render_track_panel(track: dict) -> None:
    votes = track.get("class_votes") or {}
    vote_text = ", ".join(f"{name} {count}" for name, count in votes.items()) or "none"
    st.subheader(track.get("track_id"))
    st.write(f"class: {track.get('class')}")
    st.write(f"class_votes: {vote_text}")
    st.write(f"t_start: {format_time(track.get('t_start'))}")
    st.write(f"t_end: {format_time(track.get('t_end'))}")
    st.write(f"n_frames: {track.get('n_frames')}")
    st.write(f"fragmented: {show_value(track.get('fragmented'))}")


def render_coverage_panel(evidence: dict, rule: str) -> None:
    ranges = (evidence.get("coverage") or {}).get(rule) or []
    eligible = (evidence.get("negative_eligible") or {}).get(rule)
    summary = evidence.get("detector_summary") or {}
    st.subheader(f"Evidence for COV-{rule}")
    if ranges:
        shown = ", ".join(format_span(start, end) for start, end in ranges)
    else:
        shown = "none"
    st.write(f"rule: {rule}")
    st.write(f"time ranges covered: {shown}")
    st.write(f"negative_eligible: {show_value(eligible)}")
    st.write(f"person tracks: {summary.get('person_tracks', 0)}")
    st.write(f"bag tracks: {summary.get('bag_tracks', 0)}")
    st.write(COV_SENTENCE)


def render_evidence_panel(clip_id: str, evidence: dict, answer: dict | None, question: str, key_prefix: str) -> None:
    ref = st.session_state.get("selected_ref")
    if not ref:
        st.subheader("Evidence")
        st.write("Select a cited ID to open the evidence panel.")
        return
    if ref.startswith("EV-"):
        event = next((item for item in evidence.get("events") or [] if item.get("event_id") == ref), None)
        if event is None:
            st.write("This ID is not in the current evidence package.")
            return
        render_event_panel(clip_id, evidence, event, answer or {}, question, key_prefix)
        return
    if ref.startswith("TRK-"):
        track = next((item for item in evidence.get("tracks") or [] if item.get("track_id") == ref), None)
        if track is None:
            st.write("This ID is not in the current evidence package.")
            return
        render_track_panel(track)
        return
    if ref.startswith("COV-"):
        render_coverage_panel(evidence, ref[4:])
        return
    st.write("This ID is not an event, track, or coverage ID.")


def render_answer_block(answer: dict, evidence: dict, clip_id: str, question: str, source_kind: str, when: str | None, key_prefix: str) -> None:
    focus_first_cited(answer)
    source_text = source_text_for(source_kind, when)
    render_answer_card(answer, clip_id, question, key_prefix)
    caveat = no_caveat(answer, evidence, question)
    if caveat:
        st.markdown(f"<div class='el-caveat'>{html.escape(caveat)}</div>", unsafe_allow_html=True)
    banner_html("el-amber", AMBER)
    render_checks(check_lines(answer, evidence, source_text))
    render_abstention(answer, evidence, question)
    if answer.get("status") == "api_error" and st.button("Retry", key="ask-retry"):
        st.session_state.do_ask = True
        st.rerun()


def run_live_ask(clip_id: str, question: str) -> dict | None:
    slot: dict = {}
    holder = st.empty()
    started = time.perf_counter()

    def target() -> None:
        try:
            slot["result"] = ask_cached(clip_id, question)
        except BaseException as exc:
            slot["error"] = public_text(str(exc))

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    with st.spinner("Asking…"):
        while worker.is_alive():
            seconds = f"{time.perf_counter() - started:.0f}"
            holder.markdown(loading_html(seconds), unsafe_allow_html=True)
            time.sleep(0.4)
    worker.join()
    holder.empty()
    if "error" in slot:
        banner_html("el-api", "API error. This is not an abstention.")
        st.text(slot["error"])
        return None
    return slot.get("result")


def loading_html(seconds: str) -> str:
    return (
        "<div class='el-skel-wrap'>"
        "<div class='el-skel' style='width:46%'></div>"
        "<div class='el-skel' style='width:88%'></div>"
        "<div class='el-skel' style='width:62%'></div>"
        f"<p class='el-asking'>Asking… {html.escape(seconds)} s</p>"
        "</div>"
    )


def sample_api_error() -> dict:
    return {
        "decision": None,
        "abstained": False,
        "reason": None,
        "status": "api_error",
        "claims": [],
        "human_review_required": True,
        "_api_errors": ["Sample layout. The service did not return an answer."],
        "_validated": False,
    }


def page_header(crumb: str, title: str, subtitle: str) -> None:
    st.markdown(
        "<div class='el-band'>"
        f"<p class='el-crumb'>{html.escape(crumb)}</p>"
        f"<h1 class='el-title'>{html.escape(title)}</h1>"
        f"<p class='el-sub'>{html.escape(subtitle)}</p></div>",
        unsafe_allow_html=True,
    )


def verdict_kind(answer: dict) -> str:
    if answer.get("status") == "api_error":
        return "error"
    if answer.get("abstained") or answer.get("decision") in (None, "cannot_determine"):
        return "abstain"
    if answer.get("decision") == "yes":
        return "yes"
    if answer.get("decision") == "no":
        return "no"
    return "abstain"


def answer_mount_key(clip_id: str, question: str, answer: dict) -> str:
    raw = "|".join(
        [
            clip_id,
            question,
            str(answer.get("decision")),
            str(answer.get("status")),
            str(answer.get("reason")),
        ]
    )
    return "ans" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def cited_event(evidence: dict, answer: dict | None) -> dict | None:
    events = list(evidence.get("events") or [])
    if answer:
        for _index, claim in cited_pairs(answer):
            for cid in claim.get("cited_ids") or []:
                if str(cid).startswith("EV-"):
                    found = next((item for item in events if item.get("event_id") == str(cid)), None)
                    if found:
                        return found
    ref = st.session_state.get("selected_ref")
    if ref:
        found = next((item for item in events if item.get("event_id") == ref), None)
        if found:
            return found
    return events[0] if events else None


def simple_yes_line(evidence: dict, answer: dict) -> str:
    event = cited_event(evidence, answer)
    verbs = {
        "zone_intrusion": "entered the restricted area",
        "unattended_object": "left a bag behind",
    }
    if not event:
        return "Something was recorded in this clip."
    verb = verbs.get(str(event.get("type")), "was recorded")
    return (
        f"Someone {verb} between {format_time(event.get('t_start'))} "
        f"and {format_time(event.get('t_end'))}."
    )


def simple_no_line(question: str) -> str:
    rule = rule_for_question(question)
    if rule == "unattended_object":
        return "No left-behind bag found."
    if rule == "fall":
        return "No fall found."
    return "No entry found."


def coverage_note(evidence: dict, answer: dict, question: str) -> str:
    rule = cited_rule(answer, evidence, question)
    row = rule_gap_row(evidence, rule)
    ranges = (evidence.get("coverage") or {}).get(rule) or []
    if not ranges:
        return f"{rule}: {row['Status']}. This is not a verified negative." if "did not run" in str(row["Status"]) else f"{rule}: {row['Status']}"
    spans = ", ".join(format_span(start, end) for start, end in ranges)
    return f"{rule}: {row['Status']} ({spans})"


def checked_markup(answer: dict, evidence: dict, kind: str, when: str | None, technical: bool) -> str:
    lines = check_lines(answer, evidence, source_text_for(kind, when))
    judged = [item for item in lines if item[0] in ("pass", "fail")]
    passed = sum(1 for item in judged if item[0] == "pass")
    total = len(judged)
    ok = bool(total) and passed == total
    mark = "✓" if ok else "✗"
    css = "el-chip-ok" if ok else "el-chip-bad"
    chips = f"<span class='el-chip {css}'>{mark} Checked · {passed} of {total}</span>"
    chips += f"<span class='el-chip el-chip-warn'>{html.escape(REVIEW_CHIP)}</span>"
    if technical:
        chips += f"<span class='el-chip el-chip-mute'>{html.escape(source_text_for(kind, when))}</span>"
    return chips


def event_tag_html(event: dict | None, technical: bool) -> str:
    if not event:
        return ""
    if technical:
        kind = str(event.get("type") or "event").replace("_", " ").upper()
        text = f"{kind} · {event.get('event_id')}"
    elif event.get("type") == "zone_intrusion":
        text = "Someone is inside the restricted area"
    elif event.get("type") == "unattended_object":
        text = "A bag was left behind"
    else:
        text = "Something was recorded"
    return f"<p class='el-tag'>{html.escape(text)}</p>"


def falls_line(evidence: dict) -> str:
    extra = max(0, len(evidence.get("events") or []) - 1)
    if extra == 0:
        return f"No other events were found. {FALL_NOTE}"
    word = "event" if extra == 1 else "events"
    return f"{extra} other {word} are listed in Technical view. {FALL_NOTE}"


def render_model_box(answer: dict, clip_id: str, key_prefix: str) -> None:
    claims = answer.get("claims") or []
    if not claims:
        st.markdown("<div class='el-mono-box'>No claim text.</div>", unsafe_allow_html=True)
        return
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            st.write(str(claim))
            continue
        st.markdown(
            f"<div class='el-mono-box'>{html.escape(str(claim.get('text') or ''))}</div>",
            unsafe_allow_html=True,
        )
        cited = [str(cid) for cid in (claim.get("cited_ids") or [])]
        if not cited:
            continue
        chip_cols = st.columns(len(cited))
        for chip_col, cid in zip(chip_cols, cited):
            with chip_col:
                if st.button(cid, key=f"{key_prefix}-cite-{clip_id}-{index}-{cid}"):
                    st.session_state.selected_ref = cid
                    st.rerun()


def render_plain_frames(clip_id: str, event: dict) -> None:
    zone = event.get("type") == "zone_intrusion"
    titles = {
        "start": "Enters" if zone else "Start",
        "peak": "Inside the area" if zone else "During the event",
        "end": "Leaves" if zone else "End",
    }
    slot_of = {
        "start": "start",
        "static": "start",
        "end": "end",
        "fire": "end",
        "owner_away": "peak",
        "peak": "peak",
    }
    by_slot: dict[str, tuple[str, str]] = {}
    labelled = moment_labels(str(event.get("event_id") or "event"), list(event.get("supporting_frames") or []))
    for rel, _caption, suffix in labelled:
        slot = slot_of.get(suffix)
        if slot and slot not in by_slot:
            by_slot[slot] = (rel, suffix)
    st.markdown("<h2 class='el-section'>What the camera saw</h2>", unsafe_allow_html=True)
    columns = st.columns(3)
    for column, slot in zip(columns, ("start", "peak", "end")):
        with column:
            title = titles[slot]
            found = by_slot.get(slot)
            if found is None and slot == "peak":
                start = float(event.get("t_start") or 0)
                end = float(event.get("t_end") or start)
                mid = (start + end) / 2
                frame = frame_at_time(CLIPS_ROOT / f"{clip_id}.mp4", mid)
                if frame is not None:
                    st.image(frame, caption=f"{title} · {format_time(mid)}")
                else:
                    st.write(f"{title}: frame could not be read")
                continue
            if found is None:
                st.write(f"{title}: not in the evidence package")
                continue
            rel, suffix = found
            path = EVIDENCE_ROOT / clip_id / rel
            if slot == "end":
                stamp = format_time(event.get("t_end"))
            elif slot == "start":
                stamp = format_time(event.get("t_start"))
            else:
                stamp = moment_time(event, suffix)
            caption = f"{title} · {stamp}"
            if path.is_file():
                st.image(str(path), caption=caption)
            else:
                st.write(f"{caption} — file missing")


def render_simple_verdict(
    answer: dict,
    evidence: dict,
    clip_id: str,
    question: str,
    kind: str,
    when: str | None,
    prefix: str,
    technical: bool,
) -> None:
    outcome = verdict_kind(answer)
    with st.container(key=answer_mount_key(clip_id, question, answer)):
        if outcome == "error":
            st.markdown(
                "<div class='el-api'>Could not reach the language model. Try again.</div>",
                unsafe_allow_html=True,
            )
            for message in answer.get("_api_errors") or []:
                st.text(public_text(str(message)))
            sample = any("Sample layout" in str(item) for item in (answer.get("_api_errors") or []))
            if not sample and st.button("Retry", key="ask-retry"):
                st.session_state.do_ask = True
                st.rerun()
            return
        if outcome == "yes":
            word, mark, box, badge = "Yes", "✓", "el-v-yes", "el-badge-yes"
            sentence = simple_yes_line(evidence, answer)
        elif outcome == "no":
            word, mark, box, badge = "No", "–", "el-v-no", "el-badge-no"
            sentence = simple_no_line(question)
        else:
            word, mark, box, badge = "Can't tell", "?", "el-v-abstain", "el-badge-abstain"
            sentence = "Can't tell from this clip."
        chips = checked_markup(answer, evidence, kind, when, technical)
        st.markdown(
            f"<div class='el-verdict {box}'>"
            f"<div class='el-badge-pop {badge}'>{mark}</div><div>"
            f"<p class='el-verdict-word'>{word}</p>"
            f"<p class='el-answer-line'>{html.escape(sentence)}</p>"
            f"<div>{chips}</div></div></div>",
            unsafe_allow_html=True,
        )
        if outcome == "no":
            caveat = no_caveat(answer, evidence, question)
            if caveat:
                st.markdown(f"<div class='el-caveat'>{html.escape(caveat)}</div>", unsafe_allow_html=True)
            st.caption(coverage_note(evidence, answer, question))
        if outcome == "abstain":
            st.write(abstention_plain(evidence, question))
        event = cited_event(evidence, answer)
        if event is not None:
            if st.button("Watch this moment", key=f"watch-{prefix}-{clip_id}"):
                st.session_state.selected_ref = event.get("event_id")
                st.session_state.watch_start = float(event.get("t_start") or 0)
                st.rerun()
        st.markdown("<p class='el-kicker'>Is this correct?</p>", unsafe_allow_html=True)
        render_verdict(
            clip_id,
            question,
            claim_index_for(answer, str((event or {}).get("event_id") or "")),
            f"{prefix}-card",
            reject_label="Flag",
        )


def render_technical_lower(
    answer: dict,
    evidence: dict,
    clip_id: str,
    question: str,
    kind: str,
    when: str | None,
    prefix: str,
) -> None:
    if answer.get("status") == "api_error":
        return
    render_model_box(answer, clip_id, prefix)
    banner_html("el-amber", AMBER)
    render_checks(check_lines(answer, evidence, source_text_for(kind, when)))
    render_abstention(answer, evidence, question)
    render_evidence_panel(clip_id, evidence, answer, question, prefix)


def render_modes() -> None:
    mode_a, mode_b, mode_c = st.columns(3)
    with mode_a:
        st.button("A — not implemented yet", disabled=True, key="mode-a")
    with mode_b:
        st.button("B — active", type="primary", key="mode-b")
    with mode_c:
        st.button("C — not implemented yet", disabled=True, key="mode-c")


def page_investigate(manifest: list[dict]) -> None:
    clips = clip_ids()
    if not clips:
        st.write("No evidence packages in data/evidence.")
        return
    if st.session_state.get("clip_id") not in clips:
        st.session_state.clip_id = clips[0]
    page_header(
        "Investigate",
        "Ask this clip",
        "Every answer is checked against the evidence. For human review · not proof.",
    )
    clip_id = st.selectbox("Clip", clips, key="clip_id")
    evidence = load_evidence(clip_id)
    video = evidence.get("video") or {}
    licence = video.get("licence") or "licence not recorded"
    st.caption(
        f"{clip_id} · {format_time(video.get('duration_s'))} · {licence}"
    )
    technical = st.session_state.get("ui_view") == "technical"
    if technical:
        render_modes()
    with st.container(border=True, key="qcard"):
        question_col, ask_col = st.columns([4, 1])
        with question_col:
            st.text_area("Question", key="question", height=68)
        question = st.session_state.question
        if st.query_params.get("clip") != clip_id:
            st.query_params["clip"] = clip_id
        if question and st.query_params.get("q") != question:
            st.query_params["q"] = question
        with ask_col:
            st.write("")
            key_ok = bool(os.environ.get("GEMINI_API_KEY"))
            if st.button("Ask", key="ask-question", type="primary", disabled=not key_ok):
                if not str(question).strip():
                    st.session_state.ask_notice = "Enter a question first."
                else:
                    st.session_state.do_ask = True
                    st.session_state.answer_view = "Ask"
                st.rerun()
        if not key_ok:
            st.caption("GEMINI_API_KEY is not available. Ask is off.")
        notice = st.session_state.pop("ask_notice", None)
        if notice:
            st.write(notice)
        st.radio("Show", ["Ask", "Replay"], key="answer_view", horizontal=True)
        samples = clip_questions(clip_id, evidence)
        if samples:
            st.markdown("<p class='el-kicker'>Try also</p>", unsafe_allow_html=True)
            sample_cols = st.columns(len(samples))
            for index, sample in enumerate(samples):
                with sample_cols[index]:
                    if st.button(sample, key=f"sample-{clip_id}-{index}"):
                        st.session_state.pending_question = sample
                        st.rerun()

    loading_sample = st.query_params.get("layout") == "loading"
    answer = None
    kind = "live"
    when = None
    prefix = "ask"
    replay_saved = None
    missing_replay = False
    if not loading_sample and st.session_state.answer_view == "Replay":
        saved = find_saved(manifest, clip_id, question)
        if saved is None:
            missing_replay = True
        else:
            answer = saved.get("answer_json") or {}
            kind = "replay"
            when = str(saved.get("run_time") or "")
            prefix = "replay"
            replay_saved = saved
    elif not loading_sample:
        if st.query_params.get("layout") == "api_error":
            answer = sample_api_error()
        else:
            asking = st.session_state.pop("do_ask", False)
            stored = st.session_state.get("ask_result") or {}
            same = (
                stored.get("clip_id") == clip_id
                and stored.get("question") == question
                and stored.get("result")
            )
            if asking or not same:
                cached = lookup_cached(clip_id, question) if str(question).strip() else None
                if cached is not None:
                    st.session_state.ask_result = {
                        "clip_id": clip_id,
                        "question": question,
                        "result": cached,
                    }
                elif asking:
                    st.session_state.ask_result = {
                        "clip_id": clip_id,
                        "question": question,
                        "result": run_live_ask(clip_id, question),
                    }
                else:
                    st.session_state.ask_result = None
            stored = st.session_state.get("ask_result") or {}
            if stored.get("clip_id") == clip_id and stored.get("question") == question and stored.get("result"):
                result = stored["result"]
                answer = result.get("answer") or {}
                kind = "cached" if result.get("source") == "cached" else "live"
                when = result.get("cached_at")
    if answer:
        focus_first_cited(answer)
    event = cited_event(evidence, answer) if answer else None
    left, right = st.columns([5, 7])
    with left:
        if loading_sample:
            banner_html("el-amber", "Sample layout. Not a live result.")
            st.markdown(loading_html("12"), unsafe_allow_html=True)
        elif missing_replay:
            st.write("no saved run for this clip and question")
        elif answer:
            if replay_saved is not None:
                banner_html(
                    "el-replay",
                    "REPLAY of a saved real run: "
                    f"{replay_saved.get('run_time')}, model {replay_saved.get('model')}",
                )
                with st.expander("console log from the saved run"):
                    st.text(replay_saved.get("console_log") or "")
            if st.query_params.get("layout") == "api_error":
                banner_html("el-amber", "Sample layout. Not a live result.")
            render_simple_verdict(answer, evidence, clip_id, question, kind, when, prefix, technical)
        else:
            st.write("Ask a question about this clip. A saved or cached answer appears here.")
    with right:
        if event:
            st.markdown(event_tag_html(event, technical), unsafe_allow_html=True)
        show_clip_video(
            clip_id,
            evidence,
            start_time=st.session_state.get("watch_start"),
            plain=not technical,
            playhead_id=str(event.get("event_id")) if event else None,
        )
    if answer and not loading_sample and answer.get("status") != "api_error":
        if event:
            render_plain_frames(clip_id, event)
        st.write(falls_line(evidence))
        if technical:
            render_technical_lower(answer, evidence, clip_id, question, kind, when, prefix)
        else:
            with st.expander("Show technical details"):
                st.caption("IDs, the validator list, and the rule trace.")
                render_technical_lower(answer, evidence, clip_id, question, kind, when, prefix)


def zone_polygons(zones: list) -> list:
    polygons = []
    for zone in zones or []:
        poly = zone.get("polygon") if isinstance(zone, dict) else None
        if poly and len(poly) >= 3:
            polygons.append(poly)
    return polygons


def first_frame(clip_path: Path, polygons: list):
    import cv2
    import numpy as np

    if not clip_path.is_file():
        return None
    capture = cv2.VideoCapture(str(clip_path))
    ok, frame = capture.read()
    capture.release()
    if not ok or frame is None:
        return None
    for poly in polygons:
        points = np.array(poly, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(frame, [points], True, (0, 220, 255), 2)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def load_clip_meta() -> dict:
    return json.loads(CLIP_META_PATH.read_text(encoding="utf-8"))


def is_caviar(clip_id: str, video: dict | None) -> bool:
    source = str((video or {}).get("source_dataset") or "")
    return source.upper() == "CAVIAR" or clip_id.startswith("cav")


def recorded_by_you(clip_id: str, group_name: str) -> bool:
    return group_name == "Recorded and uploaded" or clip_id.startswith("live_")


def render_clip_card(clip_id: str, record: dict, group_name: str) -> None:
    title = str(record.get("title") or clip_id)
    note = str(record.get("note") or "")
    st.markdown("<div class='el-card-marker'></div>", unsafe_allow_html=True)
    evidence_path = EVIDENCE_ROOT / clip_id / "evidence.json"
    ready = evidence_path.is_file()
    evidence = load_evidence(clip_id) if ready else {}
    video = evidence.get("video") or {}
    events = list(evidence.get("events") or [])
    if ready:
        polygons = zone_polygons(evidence.get("zones") or [])
        frame = first_frame(CLIPS_ROOT / f"{clip_id}.mp4", polygons)
        if frame is not None:
            caption = f"{title} first frame"
            caption += " with zone polygon" if polygons else ", no zone defined"
            st.image(frame, caption=caption)
        else:
            st.markdown("<div class='el-ph'>No preview</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='el-ph'>No preview</div>", unsafe_allow_html=True)
    st.markdown(f"### {html.escape(title)}")
    st.markdown(f"<p class='el-clip-id'>{html.escape(clip_id)}</p>", unsafe_allow_html=True)
    chips = []
    if ready:
        chips.append("<span class='el-chip el-chip-ok'>Evidence ready</span>")
        if events:
            chips.append(f"<span class='el-chip el-chip-info'>{len(events)} events</span>")
        else:
            chips.append("<span class='el-chip el-chip-warn'>No events</span>")
    else:
        chips.append("<span class='el-chip el-chip-warn'>No evidence package yet</span>")
    if recorded_by_you(clip_id, group_name):
        chips.append("<span class='el-chip el-chip-mute'>Recorded by you</span>")
    elif video.get("source_dataset"):
        chips.append(
            f"<span class='el-chip el-chip-mute'>{html.escape(str(video.get('source_dataset')))}</span>"
        )
    st.markdown("".join(chips), unsafe_allow_html=True)
    if note:
        st.markdown(f"<p class='el-note'>{html.escape(note)}</p>", unsafe_allow_html=True)
    if ready:
        provenance = evidence.get("provenance") or {}
        licence = video.get("licence") or "licence not recorded"
        st.caption(
            f"{format_time(video.get('duration_s'))} · {licence} · "
            f"processed {short_stamp(provenance.get('run_time_utc'))}"
        )
        if is_caviar(clip_id, video):
            st.caption(CAVIAR_NOTE)
        open_col, report_col = st.columns(2)
        with open_col:
            if st.button("Investigate", key=f"open-{clip_id}"):
                st.session_state.nav_screen = "Investigate"
                st.session_state.nav_clip = clip_id
                st.rerun()
        with report_col:
            if st.button("Report", key=f"report-{clip_id}"):
                st.session_state.nav_screen = "Incident report"
                st.session_state.nav_clip = clip_id
                st.rerun()
    else:
        st.button("Investigate", key=f"open-{clip_id}", disabled=True)
        st.caption("Process this clip")
        if is_caviar(clip_id, None):
            st.caption(CAVIAR_NOTE)


def page_library() -> None:
    page_header("Library", "Clip library", "Grouped clips. Open one to ask a question.")
    if not CLIP_META_PATH.is_file():
        st.write("data/clips_meta.json is missing.")
        return
    st.text_input("Search", key="library_query", placeholder="Search by title or clip id")
    st.radio(
        "Filter",
        ["All", "Evidence ready", "Recorded by you"],
        key="library_filter",
        horizontal=True,
    )
    meta = load_clip_meta()
    clips = meta.get("clips") or {}
    query = str(st.session_state.get("library_query") or "").strip().lower()
    chosen = st.session_state.get("library_filter") or "All"
    for group in meta.get("group_order") or []:
        name = str(group.get("name") or "Clips")
        visible = []
        for clip_id in group.get("clips") or []:
            clip_id = str(clip_id)
            record = clips.get(clip_id) or {}
            blob = f"{record.get('title') or ''} {clip_id} {record.get('note') or ''}".lower()
            if query and query not in blob:
                continue
            ready = (EVIDENCE_ROOT / clip_id / "evidence.json").is_file()
            if chosen == "Evidence ready" and not ready:
                continue
            if chosen == "Recorded by you" and not recorded_by_you(clip_id, name):
                continue
            visible.append((clip_id, record))
        if not visible:
            continue
        expanded = (not group.get("collapsed")) or bool(query) or chosen != "All"
        with st.expander(f"{name} · {len(visible)}", expanded=expanded):
            for start in range(0, len(visible), 3):
                columns = st.columns(3)
                for column, (clip_id, record) in zip(columns, visible[start:start + 3]):
                    with column:
                        render_clip_card(clip_id, record, name)


def event_row(evidence: dict, event: dict) -> dict:
    zone = ""
    dwell = ""
    if event.get("type") == "zone_intrusion":
        zone = zone_name(evidence, event.get("zone_id"))
        dwell = format_time(float(event.get("t_end") or 0) - float(event.get("t_start") or 0))
    return {
        "Event": event.get("event_id"),
        "Type": event.get("type"),
        "Time": format_span(event.get("t_start"), event.get("t_end")),
        "Conf.": event.get("confidence"),
        "Status": event.get("status"),
        "Zone": zone,
        "Dwell": dwell,
    }


def report_lines(clip_id: str, evidence: dict) -> list[str]:
    version = (evidence.get("schema_version") or "2.0")
    lines = [
        f"# Incident report: {clip_id}",
        "",
        f"{AMBER} Clip: {clip_id}. Generated from evidence package {version}.",
        "",
        "## Events",
        "",
        "| Event | Type | Time | Conf. | Status | Zone | Dwell |",
        "|---|---|---|---|---|---|---|",
    ]
    for event in evidence.get("events") or []:
        row = event_row(evidence, event)
        lines.append(
            f"| {row['Event']} | {row['Type']} | {row['Time']} | {row['Conf.']} | "
            f"{row['Status']} | {row['Zone']} | {row['Dwell']} |"
        )
    for rule in RULES:
        if events_for_rule(evidence, rule):
            continue
        row = rule_gap_row(evidence, rule)
        lines.append(
            f"| {row['Event']} | {row['Type']} | {row['Time']} | {row['Conf.']} | "
            f"{row['Status']} | {row['Zone']} | {row['Dwell']} |"
        )
    lines.extend(["", "## Supporting frames", ""])
    any_frame = False
    for event in evidence.get("events") or []:
        for rel, caption, _suffix in moment_labels(str(event.get("event_id")), list(event.get("supporting_frames") or [])):
            any_frame = True
            lines.append(f"- data/evidence/{clip_id}/{rel} — {caption}")
    if not any_frame:
        lines.append("- none")
    lines.extend(["", "## Limits", "", f"- {LIMITS_LINE}", ""])
    return lines


PLAIN_RULE = {
    "unattended_object": "Left-behind bag",
    "zone_intrusion": "Restricted-zone entry",
    "fall": "Fall",
}
PLAIN_STATUS = {"confirmed_by_rule": "Confirmed by rule"}
REPORT_PACK_LABEL = "v2.0"
FRAME_SLOTS = ("start", "peak", "end")


def plain_rule_name(rule: str) -> str:
    return PLAIN_RULE.get(rule, rule.replace("_", " "))


def plain_status_name(status: str) -> str:
    return PLAIN_STATUS.get(status, str(status or "").replace("_", " "))


def number_text(value) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def event_reviews(clip_id: str) -> dict[str, dict]:
    """Latest reviewer verdict for each event. Reads the log and the answer cache only."""
    answers: dict[str, dict] = {}
    folder = ROOT / "data" / "llm_cache"
    if folder.is_dir():
        for path in folder.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("clip_id") != clip_id:
                continue
            question = str(data.get("question") or "")
            stamp = str(data.get("timestamp") or "")
            previous = answers.get(question)
            if previous is None or stamp >= str(previous.get("_stamp") or ""):
                answer = dict(data.get("answer") or {})
                answer["_stamp"] = stamp
                answers[question] = answer
    latest: dict[str, dict] = {}
    if not REVIEW_LOG.is_file():
        return latest
    for line in REVIEW_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("clip_id") != clip_id:
            continue
        answer = answers.get(str(row.get("question") or "")) or {}
        claims = answer.get("claims") or []
        index = row.get("claim_index")
        if not isinstance(index, int) or index < 0 or index >= len(claims):
            continue
        claim = claims[index]
        if not isinstance(claim, dict):
            continue
        stamp = str(row.get("timestamp") or "")
        for cid in claim.get("cited_ids") or []:
            event_id = str(cid)
            if not event_id.startswith("EV-"):
                continue
            previous = latest.get(event_id)
            if previous is None or stamp >= str(previous.get("timestamp") or ""):
                latest[event_id] = {"verdict": str(row.get("verdict") or ""), "timestamp": stamp}
    return latest


def fact_rows(evidence: dict, event: dict) -> list[tuple[str, str]]:
    """Rows that have a value for this event. Empty zone or dwell cells are omitted."""
    rule = str(event.get("type") or event.get("rule_id") or "")
    rows = [("Rule", plain_rule_name(rule))]
    if event.get("t_start") is not None and event.get("t_end") is not None:
        rows.append(("Time range", format_span(event.get("t_start"), event.get("t_end"))))
    if rule == "zone_intrusion" and event.get("t_start") is not None and event.get("t_end") is not None:
        dwell = float(event.get("t_end") or 0) - float(event.get("t_start") or 0)
        minimum = (event.get("thresholds") or {}).get("dwell_min_s")
        if minimum is None:
            minimum = THRESHOLDS["intrusion_dwell_s"]
        rows.append(("Dwell", f"{number_text(dwell)} s, minimum {number_text(float(minimum))} s"))
    if event.get("confidence") is not None:
        floor = (event.get("thresholds") or {}).get("conf_min")
        if floor is None:
            floor = (evidence.get("provenance") or {}).get("conf_threshold")
        text = number_text(float(event.get("confidence")))
        if floor is not None:
            text = f"{text}, floor {number_text(float(floor))}"
        rows.append(("Confidence", text))
    if event.get("zone_id"):
        rows.append(("Zone", f"{zone_name(evidence, event.get('zone_id'))} ({event.get('zone_id')})"))
    tracks = []
    if event.get("object_track_id"):
        tracks.append(f"{event.get('object_track_id')} object")
    if event.get("owner_track_id"):
        tracks.append(f"{event.get('owner_track_id')} owner")
    if not tracks:
        tracks = [str(item) for item in (event.get("track_ids") or []) if item]
    if event.get("track_id") and not tracks:
        tracks = [str(event.get("track_id"))]
    if tracks:
        rows.append(("Track", ", ".join(tracks)))
    return rows


def not_checked_lines(evidence: dict) -> list[str]:
    """Coverage and eligibility, not events. A rule that did not run stays out of the event list."""
    lines = [FALL_NOTE]
    coverage = evidence.get("coverage") or {}
    eligible = evidence.get("negative_eligible") or {}
    summary = evidence.get("detector_summary") or {}
    labels = {
        "zone_intrusion": "restricted-zone",
        "unattended_object": "left-behind-bag",
    }
    for rule in ("zone_intrusion", "unattended_object"):
        if events_for_rule(evidence, rule):
            continue
        ranges = coverage.get(rule) or []
        label = labels[rule]
        if not ranges:
            if rule == "zone_intrusion":
                lines.append("The restricted-zone rule did not run. No zone was set on this clip.")
            else:
                lines.append("The left-behind-bag rule did not run on this clip.")
            continue
        start = min(float(span[0]) for span in ranges)
        end = max(float(span[1]) for span in ranges)
        span = format_span(start, end)
        if eligible.get(rule) is False:
            if rule == "unattended_object":
                bags = int(summary.get("bag_tracks") or 0)
                lines.append(
                    f"The left-behind-bag rule ran over {span}, but no bag was detected "
                    f"({bags} bag tracks), so this could not be verified."
                )
            else:
                lines.append(
                    f"The restricted-zone rule ran over {span}, but negative_eligible is false, "
                    "so a verified negative was not available."
                )
        elif eligible.get(rule) is True:
            lines.append(
                f"The {label} rule ran over {span} and recorded no event. "
                "That coverage is not proof that nothing happened."
            )
    dwell = float(THRESHOLDS["intrusion_dwell_s"])
    lines.append(
        f"Entries shorter than {dwell:.1f} s can be missed. "
        f"The zone rule only keeps a dwell of at least {dwell:.1f} s."
    )
    return lines


def review_note(review: dict | None) -> str:
    if not review or not review.get("verdict"):
        return "Not reviewed. No reviewer note was saved."
    when = short_stamp(str(review.get("timestamp") or ""))
    return f"{review.get('verdict')} on {when}. No reviewer note was saved."


def page_report() -> None:
    clips = clip_ids()
    if not clips:
        st.write("No evidence packages in data/evidence.")
        return
    if st.session_state.get("clip_id") not in clips:
        st.session_state.clip_id = clips[0]
    with st.container(key="reportband"):
        title_col, pick_col = st.columns([3, 2])
        with title_col:
            st.markdown(
                "<p class='el-crumb'>Report</p><h1 class='el-title'>Incident report</h1>",
                unsafe_allow_html=True,
            )
        with pick_col:
            clip_id = st.selectbox("Clip", clips, key="clip_id")
    if st.query_params.get("clip") != clip_id:
        st.query_params["clip"] = clip_id
    evidence = load_evidence(clip_id)
    banner_html(
        "el-amber",
        f"{REVIEW_CHIP} · {clip_id} · Generated from evidence package {REPORT_PACK_LABEL}",
    )
    events = list(evidence.get("events") or [])
    reviews = event_reviews(clip_id)
    confirmed = sum(1 for event in events if reviews.get(str(event.get("event_id")), {}).get("verdict") == "Confirmed")
    rejected = sum(1 for event in events if reviews.get(str(event.get("event_id")), {}).get("verdict") == "Rejected")
    pending = len(events) - confirmed - rejected
    stats = (
        ("Events found", len(events), "0ms"),
        ("Confirmed", confirmed, "60ms"),
        ("Rejected", rejected, "120ms"),
        ("Not reviewed", pending, "180ms"),
    )
    cards = "".join(
        "<article class='el-stat' style='animation-delay:"
        f"{delay}'><p class='el-kicker'>{html.escape(label)}</p>"
        f"<p class='el-stat-n'>{count}</p></article>"
        for label, count, delay in stats
    )
    st.markdown(
        f"<section class='el-report-sec'><div class='el-report-stats'>{cards}</div></section>",
        unsafe_allow_html=True,
    )
    if not events:
        st.markdown(
            "<section class='el-report-sec' style='animation-delay:240ms'>"
            "<h2 class='el-report-h'>No events found by the rules</h2>"
            "<p class='el-report-note'>The rules recorded no event on this clip. "
            "Coverage is listed below. This is not a claim that nothing happened.</p></section>",
            unsafe_allow_html=True,
        )
    for index, event in enumerate(events):
        event_id = str(event.get("event_id") or "")
        rule = str(event.get("type") or event.get("rule_id") or "")
        status = str(event.get("status") or "")
        review = reviews.get(event_id)
        verdict = (review or {}).get("verdict") or "Not reviewed"
        chip = {"Confirmed": "el-chip-ok", "Rejected": "el-chip-bad"}.get(verdict, "el-chip-mute")
        with st.container(key=f"rpt-{index}-{event_id}"):
            st.markdown(
                f"<h2 class='el-report-h'>{html.escape(plain_rule_name(rule))}</h2>"
                f"<p><span class='el-chip el-mono'>{html.escape(event_id)}</span>"
                f"<span class='el-chip el-mono'>{html.escape(rule)}</span>"
                f"<span class='el-chip el-chip-info'>{html.escape(plain_status_name(status))}</span>"
                f"<span class='el-chip el-mono'>{html.escape(status)}</span>"
                f"<span class='el-chip {chip}'>{html.escape(verdict)}</span></p>",
                unsafe_allow_html=True,
            )
            labelled = moment_labels(event_id, list(event.get("supporting_frames") or []))
            found: dict[str, tuple[str, str]] = {}
            for rel, caption, suffix in labelled:
                slot = caption.rsplit(" ", 1)[-1]
                found[slot] = (rel, suffix)
            columns = st.columns(3)
            for column, slot in zip(columns, FRAME_SLOTS):
                with column:
                    saved = found.get(slot)
                    if saved is None:
                        st.markdown(f"<div class='el-miss'>{html.escape(slot)} frame not saved</div>", unsafe_allow_html=True)
                        continue
                    rel, suffix = saved
                    path = EVIDENCE_ROOT / clip_id / rel
                    if suffix == "fire":
                        caption_text = f"end · fire at {format_time(event.get('t_start'))}"
                    else:
                        caption_text = f"{slot} · {moment_time(event, suffix)}"
                    if path.is_file():
                        st.image(str(path), caption=caption_text)
                    else:
                        st.markdown(
                            f"<div class='el-miss'>{html.escape(caption_text)} — file missing</div>",
                            unsafe_allow_html=True,
                        )
            body = "".join(
                f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
                for label, value in fact_rows(evidence, event)
            )
            trace = str(event.get("rule_trace") or "")
            st.markdown(
                f"<table class='el-table'><tbody>{body}</tbody></table>"
                f"<p class='el-kicker'>Rule trace</p><div class='el-mono-box'>{html.escape(trace)}</div>"
                f"<p class='el-kicker'>Reviewer note</p><p class='el-report-note'>{html.escape(review_note(review))}</p>",
                unsafe_allow_html=True,
            )
    missed = "".join(f"<li>{html.escape(line)}</li>" for line in not_checked_lines(evidence))
    st.markdown(
        "<section class='el-report-sec' style='animation-delay:240ms'>"
        "<h2 class='el-report-h'>What was not checked</h2>"
        f"<ul>{missed}</ul></section>",
        unsafe_allow_html=True,
    )
    markdown = "\n".join(report_lines(clip_id, evidence))
    download_col, back_col, _spacer = st.columns([1, 1, 2])
    with download_col:
        st.download_button(
            "Download report",
            data=markdown,
            file_name=f"{clip_id}_incident_report.md",
            mime="text/markdown",
            key=f"download-{clip_id}",
        )
    with back_col:
        if st.button("Back to Investigate", key="report-back"):
            st.session_state.nav_screen = "Investigate"
            st.rerun()


def run_command(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True)


def command_with_elapsed(command: list[str], label: str) -> subprocess.CompletedProcess:
    """Run a subprocess and show elapsed seconds. Does not call Gemini."""
    slot: dict = {}
    holder = st.empty()
    started = time.perf_counter()

    def target() -> None:
        slot["result"] = run_command(command)

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    while worker.is_alive():
        holder.markdown(f"**{label}… {time.perf_counter() - started:.0f} s**")
        time.sleep(0.4)
    worker.join()
    holder.empty()
    if "result" in slot:
        return slot["result"]
    return subprocess.CompletedProcess(command, 1, "", "The command did not finish.")


def run_followed(command: list[str]) -> subprocess.CompletedProcess:
    """Run a subprocess and show its stage= lines with elapsed seconds."""
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    lock = threading.Lock()

    def reader() -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            with lock:
                lines.append(line)

    worker = threading.Thread(target=reader, daemon=True)
    worker.start()
    holder = st.empty()
    started = time.perf_counter()
    stage = "Live monitor running"
    while True:
        with lock:
            snapshot = list(lines)
        for line in snapshot:
            text = line.strip()
            if text.startswith("stage="):
                stage = text.split("=", 1)[1].strip()
        elapsed = time.perf_counter() - started
        shown = stage if stage == "Ready" or stage.endswith("...") else f"{stage}..."
        holder.markdown(f"**{shown}** {elapsed:.0f} s")
        if proc.poll() is not None:
            worker.join(timeout=2)
            break
        time.sleep(0.4)
    with lock:
        stdout = "".join(lines)
    holder.empty()
    return subprocess.CompletedProcess(command, proc.returncode if proc.returncode is not None else 1, stdout, "")


def stdout_value(stdout: str, prefix: str) -> str:
    found = ""
    for line in (stdout or "").splitlines():
        if line.startswith(prefix):
            found = line.split("=", 1)[1].strip()
    return found


def show_build_summary(evidence: dict) -> None:
    summary = evidence.get("detector_summary") or {}
    video = evidence.get("video") or {}
    st.write(f"Duration: {format_time(video.get('duration_s'))}")
    st.write(f"Person tracks: {summary.get('person_tracks', 0)}")
    st.write(f"Bag tracks: {summary.get('bag_tracks', 0)}")
    events = evidence.get("events") or []
    if events:
        for event in events:
            st.write(
                f"{event.get('event_id')} {event.get('type')} "
                f"{format_span(event.get('t_start'), event.get('t_end'))}"
            )
    else:
        st.write("Events found: none recorded by the rules that ran.")
    for line in coverage_lines(evidence):
        st.write(line)


def start_live_job(licence: str, zone: Path | None) -> None:
    """Start the preview without blocking, so Stop can write the flag."""
    clear_stop_flag(stop_flag_path(ROOT))
    command = [
        sys.executable,
        str(ROOT / "live_monitor.py"),
        "--max-seconds", "100",
        "--out-dir", str(CLIPS_ROOT),
        "--licence", licence,
        "--consent-basis", CONSENT_BASIS,
    ]
    if zone is not None and zone.is_file():
        command.extend(["--zone", str(zone)])
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    lock = threading.Lock()

    def reader() -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            with lock:
                lines.append(line)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    st.session_state.live_job = {
        "proc": proc,
        "lines": lines,
        "lock": lock,
        "thread": thread,
        "started": time.perf_counter(),
    }
    st.session_state.pop("live_done", None)


def render_live_done() -> None:
    done = st.session_state.get("live_done")
    if not done:
        return
    stdout = done.get("stdout") or ""
    trimmed = stdout_value(stdout, "trimmed=")
    if trimmed:
        st.write(trimmed)
    wrote = stdout_value(stdout, "wrote=")
    if done.get("code") != 0 or not wrote:
        st.write(public_text(stdout or "The live monitor did not finish."))
        return
    st.write(f"Ready in {float(done.get('elapsed') or 0):.0f} s.")
    device = stdout_value(stdout, "device=")
    fps = stdout_value(stdout, "fps=")
    detect_fps = stdout_value(stdout, "detect_fps=")
    latency = stdout_value(stdout, "latency_ms=")
    latency_max = stdout_value(stdout, "latency_max_ms=")
    adapt = stdout_value(stdout, "adapt=")
    session_s = stdout_value(stdout, "elapsed_s=")
    if device:
        st.write(f"Device: {device}")
    if fps:
        st.write(f"Measured recording fps: {fps}")
    if detect_fps:
        st.write(f"Detection fps: {detect_fps}")
    if latency:
        st.write(f"Per-frame detection latency: {latency} ms mean, {latency_max} ms max")
    if adapt and adapt != "none":
        st.write(f"Display detection was lightened: {adapt}. The batch build does not use that size.")
    if session_s:
        st.write(f"Recorded session: {session_s} s")
    evidence_path = EVIDENCE_ROOT / Path(wrote).stem / "evidence.json"
    if not evidence_path.is_file():
        st.write("The evidence file was not written.")
        return
    show_build_summary(load_evidence(Path(wrote).stem))
    st.write("The clip is in the library and in Investigate.")


@st.fragment(run_every=0.5)
def live_running_panel() -> None:
    """Elapsed time while the window is open. Stop stays clickable on the page."""
    job = st.session_state.get("live_job")
    if not job:
        return
    proc = job["proc"]
    with job["lock"]:
        snapshot = list(job["lines"])
    stage = "Live monitor running"
    for line in snapshot:
        text = line.strip()
        if text.startswith("stage="):
            stage = text.split("=", 1)[1].strip()
    elapsed = time.perf_counter() - job["started"]
    shown = stage if stage == "Ready" or stage.endswith("...") else f"{stage}..."
    st.markdown(f"**{shown}** {elapsed:.0f} s")
    if proc.poll() is None:
        return
    job["thread"].join(timeout=2)
    with job["lock"]:
        stdout = "".join(job["lines"])
    clear_stop_flag(stop_flag_path(ROOT))
    wrote = stdout_value(stdout, "wrote=")
    if proc.returncode == 0 and wrote:
        register_new_clip(Path(wrote).stem, "live monitor recording")
        st.session_state.ready_clip = Path(wrote).stem
    st.session_state.live_done = {"stdout": stdout, "code": proc.returncode, "elapsed": elapsed}
    st.session_state.pop("live_job", None)
    st.rerun()


def probe_video(path: Path) -> dict:
    import cv2

    capture = cv2.VideoCapture(str(path))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frames = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    capture.release()
    duration = frames / fps if fps > 0 else 0.0
    return {"fps": fps, "frames": frames, "width": width, "height": height, "duration_s": duration}


def append_licence_row(row: str) -> None:
    existing = LICENCE_LOG.read_text(encoding="utf-8") if LICENCE_LOG.is_file() else ""
    with LICENCE_LOG.open("a", encoding="utf-8", newline="\n") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(row + "\n")


def register_new_clip(clip_id: str, note: str) -> None:
    if CLIP_META_PATH.is_file():
        meta = json.loads(CLIP_META_PATH.read_text(encoding="utf-8"))
    else:
        meta = {"group_order": [], "clips": {}}
    group_name = "Recorded and uploaded"
    order = meta.setdefault("group_order", [])
    found = next((group for group in order if group.get("name") == group_name), None)
    if found is None:
        found = {"name": group_name, "collapsed": False, "clips": []}
        order.append(found)
    listed = found.setdefault("clips", [])
    if clip_id not in listed:
        listed.append(clip_id)
    meta.setdefault("clips", {})[clip_id] = {
        "title": clip_id,
        "group": group_name,
        "note": note,
    }
    CLIP_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLIP_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def safe_upload_name(filename: str) -> str:
    stem = Path(filename).stem
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem).strip("_")
    return cleaned or "upload"


def coverage_lines(evidence: dict) -> list[str]:
    lines = []
    zone_ranges = (evidence.get("coverage") or {}).get("zone_intrusion") or []
    if not zone_ranges:
        lines.append(
            "zone_intrusion: the zone rule did not run, so coverage is incomplete. "
            "This is not a verified negative."
        )
    for rule in RULES:
        if rule == "zone_intrusion" and not zone_ranges:
            continue
        row = rule_gap_row(evidence, rule)
        lines.append(f"{rule}: {row['Status']} ({row['Time']})")
    return lines


def prepare_playback(clip_id: str) -> list[str]:
    """Annotated video and event extracts, so Investigate does not build them on open."""
    notes = []
    evidence = load_evidence(clip_id)
    _path, note = ensure_annotated(clip_id, evidence)
    if note:
        notes.append(note)
    for event in evidence.get("events") or []:
        _extract, event_note = ensure_event_clip(clip_id, evidence, event)
        if event_note:
            notes.append(f"{event.get('event_id')}: {event_note}")
    return notes


def page_analyse() -> None:
    st.subheader("Analyse a new clip")
    st.markdown(f"**{html.escape(ANALYSE_LABEL)}**")
    source = st.radio("Source", ["Record from webcam", "Upload a clip"], key="intake_source")
    if source == "Record from webcam":
        seconds = st.number_input("Duration (seconds)", min_value=1, max_value=60, value=20, step=1, key="record_seconds")
        if st.button("Start", key="record-start"):
            done = command_with_elapsed(
                [
                    sys.executable,
                    str(ROOT / "record_clip.py"),
                    "--seconds",
                    str(int(seconds)),
                    "--out-dir",
                    str(CLIPS_ROOT),
                ],
                "Recording",
            )
            wrote = ""
            for line in (done.stdout or "").splitlines():
                if line.startswith("wrote="):
                    wrote = line.split("=", 1)[1].strip()
            if done.returncode != 0 or not wrote:
                st.write(public_text(done.stderr or done.stdout or "The recording did not finish."))
            else:
                st.session_state.intake_path = wrote
                st.session_state.intake_kind = "webcam"
                fps_line = next((line for line in done.stdout.splitlines() if line.startswith("fps=")), "")
                st.write(public_text(f"Saved {wrote}. {fps_line}".strip()))
    else:
        upload = st.file_uploader("mp4 or avi", type=["mp4", "avi"], key="intake_upload")
        if upload is not None and st.button("Use this file", key="use-upload"):
            stem = safe_upload_name(upload.name)
            dest = CLIPS_ROOT / f"{stem}.mp4"
            suffix = 2
            while dest.exists():
                dest = CLIPS_ROOT / f"{stem}_{suffix}.mp4"
                suffix += 1
            CLIPS_ROOT.mkdir(parents=True, exist_ok=True)
            raw = dest.with_suffix(Path(upload.name).suffix.lower() or ".mp4")
            raw.write_bytes(upload.getvalue())
            if raw.suffix != ".mp4":
                ffmpeg = shutil.which("ffmpeg")
                if ffmpeg is None:
                    raw.unlink(missing_ok=True)
                    st.write("ffmpeg is not on PATH, so this avi was not converted.")
                else:
                    converted = run_command([
                        ffmpeg, "-y", "-i", str(raw),
                        "-fps_mode", "cfr", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(dest),
                    ])
                    raw.unlink(missing_ok=True)
                    if converted.returncode != 0:
                        dest.unlink(missing_ok=True)
                        st.write("ffmpeg could not convert this file to mp4.")
                        dest = None
            if dest is not None and dest.is_file():
                st.session_state.intake_path = str(dest)
                st.session_state.intake_kind = "upload"

    path_text = st.session_state.get("intake_path") or ""
    clip_path = Path(path_text) if path_text else None
    if clip_path is not None and clip_path.is_file():
        info = probe_video(clip_path)
        st.write(
            f"Clip: {clip_path.name} · {info['width']}×{info['height']} · "
            f"{format_time(info['duration_s'])} · fps {info['fps']:.2f}"
        )
        blocked = rejection_reason(info["duration_s"], info["width"], info["height"])
        if blocked:
            st.write(blocked)
    else:
        info = None
        blocked = "Choose a clip first."

    st.checkbox("people in this clip have consented / I own this clip", key="intake_consent")
    st.text_input("Licence", key="intake_licence")
    if clip_path is not None and clip_path.is_file() and st.button("Draw a restricted zone", key="draw-zone"):
        done = command_with_elapsed(
            [
                sys.executable,
                str(ROOT / "draw_zone.py"),
                str(clip_path),
                "--zone-id", "Z1",
                "--label", "restricted area",
                "--out-dir", str(ZONES_ROOT),
            ],
            "Waiting for the zone window",
        )
        zone_file = ZONES_ROOT / f"{clip_path.stem}.json"
        if done.returncode == 0 and zone_file.is_file():
            st.session_state.intake_zone = str(zone_file)
            st.write(f"Zone saved: {zone_file.name}")
        else:
            st.session_state.intake_zone = ""
            st.write(public_text(done.stdout or done.stderr or "The zone was not saved."))

    zone_text = st.session_state.get("intake_zone") or ""
    if zone_text and Path(zone_text).is_file() and clip_path is not None and Path(zone_text).stem == clip_path.stem:
        st.write(f"Zone file: {Path(zone_text).name}")
    elif clip_path is not None:
        st.write("No zone yet. Process will run without one, and the zone rule will not run.")

    if st.button("Process", key="process-clip"):
        refusal = consent_refusal(bool(st.session_state.get("intake_consent")), st.session_state.get("intake_licence") or "")
        if refusal:
            st.write(refusal)
        elif clip_path is None or not clip_path.is_file():
            st.write("Choose a clip first.")
        else:
            info = probe_video(clip_path)
            blocked = rejection_reason(info["duration_s"], info["width"], info["height"])
            if blocked:
                st.write(blocked)
            else:
                licence = str(st.session_state.get("intake_licence") or "").strip()
                kind = st.session_state.get("intake_kind") or "upload"
                append_licence_row(licence_log_row(
                    clip_path.stem,
                    "webcam" if kind == "webcam" else "upload",
                    licence,
                    "",
                    datetime.now().date().isoformat(),
                    "no, local only",
                ))
                command = [
                    sys.executable,
                    str(ROOT / "build_evidence.py"),
                    str(clip_path),
                    "--short-clip-mode",
                    "--licence", licence,
                    "--consent-basis", CONSENT_BASIS,
                    "--source-dataset", "webcam" if kind == "webcam" else "upload",
                ]
                zone_file = ZONES_ROOT / f"{clip_path.stem}.json"
                chosen = Path(str(st.session_state.get("intake_zone") or ""))
                if zone_file.is_file() and chosen.is_file() and chosen.stem == clip_path.stem:
                    command.extend(["--zone", str(zone_file)])
                started = time.perf_counter()
                done = command_with_elapsed(command, "Processing")
                elapsed = time.perf_counter() - started
                if done.returncode != 0:
                    st.write(public_text(done.stderr or done.stdout or "build_evidence.py failed."))
                else:
                    evidence = load_evidence(clip_path.stem)
                    st.write(f"Processing finished in {elapsed:.0f} s.")
                    show_build_summary(evidence)
                    media_started = time.perf_counter()
                    with st.spinner("Preparing the annotated video and event clips…"):
                        notes = prepare_playback(clip_path.stem)
                    st.write(f"Annotated video and event clips: {time.perf_counter() - media_started:.0f} s.")
                    for note in notes:
                        st.write(public_text(note))
                    note = "recorded from the webcam" if kind == "webcam" else "uploaded clip"
                    register_new_clip(clip_path.stem, note)
                    st.session_state.ready_clip = clip_path.stem
                    st.write("The clip is in the library and in Investigate.")

    st.markdown(f"**{html.escape(LIVE_LABEL)}**")
    st.write(AUTO_STOP_TEXT)
    live_zone = st.session_state.get("live_zone") or ""
    if live_zone and Path(live_zone).is_file():
        st.write(f"Live zone: {Path(live_zone).name}")
    else:
        st.write("No live zone yet. The zone rule will not run.")
    if st.button("Draw a zone on the current view", key="live-zone-draw"):
        refusal = consent_refusal(bool(st.session_state.get("intake_consent")), st.session_state.get("intake_licence") or "")
        if refusal:
            st.write(refusal)
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            still = ZONES_ROOT / "stills" / f"live_still_{stamp}.mp4"
            grabbed = command_with_elapsed(
                [sys.executable, str(ROOT / "live_monitor.py"), "--grab-still", str(still)],
                "Grabbing a still",
            )
            wrote = stdout_value(grabbed.stdout, "wrote=")
            if grabbed.returncode != 0 or not wrote:
                st.write(public_text(grabbed.stderr or grabbed.stdout or "The still was not saved."))
            else:
                drawn = command_with_elapsed(
                    [
                        sys.executable,
                        str(ROOT / "draw_zone.py"),
                        wrote,
                        "--zone-id", "Z1",
                        "--label", "restricted area",
                        "--out-dir", str(ZONES_ROOT),
                    ],
                    "Waiting for the zone window",
                )
                zone_file = ZONES_ROOT / f"{Path(wrote).stem}.json"
                if drawn.returncode == 0 and zone_file.is_file():
                    st.session_state.live_zone = str(zone_file)
                    st.write(f"Zone saved: {zone_file.name}")
                else:
                    st.session_state.live_zone = ""
                    st.write(public_text(drawn.stdout or drawn.stderr or "The zone was not saved. The zone rule will not run."))
    if st.button("Live monitor", key="live-monitor"):
        if st.session_state.get("live_job"):
            st.write("The live monitor is already running.")
        else:
            refusal = consent_refusal(bool(st.session_state.get("intake_consent")), st.session_state.get("intake_licence") or "")
            if refusal:
                st.write(refusal)
            else:
                licence = str(st.session_state.get("intake_licence") or "").strip()
                chosen_zone = Path(str(st.session_state.get("live_zone") or ""))
                start_live_job(licence, chosen_zone if chosen_zone.is_file() else None)
                st.rerun()
    if st.button("Stop live monitor", key="stop-live"):
        if st.session_state.get("live_job"):
            request_stop(stop_flag_path(ROOT))
            st.write("Stopping. The recording will be saved and processed.")
        else:
            st.write("No live monitor is running.")
    live_running_panel()
    render_live_done()
    if st.session_state.get("ready_clip") and st.button("Open Investigate", key="open-ready"):
        st.session_state.nav_screen = "Investigate"
        st.session_state.nav_clip = st.session_state.ready_clip
        st.rerun()


def render_top_bar() -> None:
    logo = (
        "<div class='el-logo'><span class='el-markbox'>"
        "<svg width='18' height='18' viewBox='0 0 24 24' fill='none' "
        "stroke='currentColor' stroke-width='2.4'>"
        "<circle cx='11' cy='11' r='7'></circle>"
        "<path d='M20 20l-3.5-3.5'></path></svg></span>"
        "<span class='el-word'>EvidenceLens</span></div>"
    )
    with st.container(horizontal=True, vertical_alignment="center", gap="small", key="topbar"):
        st.markdown(logo, unsafe_allow_html=True)
        page = st.session_state.get("page", "investigate")
        for pid, label, old in PAGES:
            key = f"navon-{pid}" if page == pid else f"nav-{pid}"
            if st.button(label, key=key):
                st.session_state.nav_screen = old
                st.rerun()
        if page == "investigate":
            view = st.session_state.get("ui_view", "simple")
            for choice, label in (("simple", "Simple"), ("technical", "Technical")):
                key = f"viewon-{choice}" if view == choice else f"view-{choice}"
                if st.button(label, key=key):
                    st.session_state.ui_view = choice
                    st.rerun()
        if st.button("Live monitor", key="top-live"):
            st.session_state.live_pop = not bool(st.session_state.get("live_pop"))
    if st.session_state.get("live_pop"):
        st.markdown(
            "<div class='el-popcard'>"
            "<p><strong>Fast lane.</strong> Provisional boxes on the live picture. Not an answer.</p>"
            "<p><strong>Answer lane.</strong> The recording is processed, then a question can be asked.</p>"
            "<p>The language model is never in the live loop. Auto-stops at 100 s.</p></div>",
            unsafe_allow_html=True,
        )
        if st.button("Open Analyse", key="live-pop-go"):
            st.session_state.nav_screen = "Analyse a new clip"
            st.session_state.live_pop = False
            st.rerun()


DEMO_CLIP = "cav_walk1"
YES_QUESTION = "Did anyone enter the restricted zone?"
NO_QUESTION = "Did anyone enter the restricted zone?"
ABSTAIN_QUESTION = "Was an object left unattended?"
HOME_START = "/app/static/home/cav_walk1_start.jpg"
HOME_END = "/app/static/home/cav_walk1_end.jpg"


def newest_saved(predicate) -> dict | None:
    """Read the answer cache. Does not call the model."""
    folder = ROOT / "data" / "llm_cache"
    best = None
    best_stamp = ""
    if not folder.is_dir():
        return None
    for path in folder.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not predicate(data):
            continue
        stamp = str(data.get("timestamp") or "")
        if best is None or stamp >= best_stamp:
            best = data
            best_stamp = stamp
    return best


def saved_for(clip_id: str, question: str) -> dict | None:
    return newest_saved(
        lambda data: data.get("clip_id") == clip_id and data.get("question") == question
    )


def claim_text(saved: dict | None) -> str:
    answer = (saved or {}).get("answer") or {}
    claims = answer.get("claims") or []
    if claims and isinstance(claims[0], dict):
        return str(claims[0].get("text") or "")
    return ""


def line_icon(body: str) -> str:
    return (
        '<svg class="el-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    )


def page_home() -> None:
    evidence = {}
    evidence_path = EVIDENCE_ROOT / DEMO_CLIP / "evidence.json"
    if evidence_path.is_file():
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    event = next(
        (item for item in (evidence.get("events") or []) if item.get("event_id") == "EV-0001"),
        None,
    )
    yes = saved_for(DEMO_CLIP, YES_QUESTION)
    no = saved_for("cav_walk2", NO_QUESTION)
    abstain = saved_for(DEMO_CLIP, ABSTAIN_QUESTION)
    yes_text = claim_text(yes)
    span = ""
    trace = ""
    if event:
        span = format_span(event.get("t_start"), event.get("t_end"))
        trace = str(event.get("rule_trace") or "")
    coverage = (evidence.get("coverage") or {}).get("zone_intrusion") or []
    covered = format_span(coverage[0][0], coverage[0][1]) if coverage else "not recorded"

    with st.container(key="homehero"):
        left, right = st.columns([5, 7])
        with left:
            st.markdown(
                "<p class='el-hero-chip'>For human review · not proof</p>"
                "<h1 class='el-hero-title'>Ask your CCTV footage. "
                "<span class='el-hero-peach'>Get answers you can check.</span></h1>"
                "<p class='el-hero-lead'>A question is answered from the evidence file for one clip. "
                "Times are copied from that file, then checked before they are shown.</p>",
                unsafe_allow_html=True,
            )
            try_col, how_col = st.columns(2)
            with try_col:
                if st.button("Try the demo", key="home-try", type="primary"):
                    st.session_state.nav_screen = "Investigate"
                    st.session_state.nav_clip = DEMO_CLIP
                    st.session_state.pending_question = YES_QUESTION
                    st.rerun()
            with how_col:
                st.markdown(
                    "<a class='el-hero-link' href='#el-how'>See how it works</a>",
                    unsafe_allow_html=True,
                )
                components.html(
                    """
                    <script>
                    const doc = window.parent.document;
                    const link = doc.querySelector("a.el-hero-link");
                    if (link && !link.dataset.bound) {
                      link.dataset.bound = "1";
                      link.addEventListener("click", function (event) {
                        const target = doc.getElementById("el-how");
                        const scroller = doc.querySelector('[data-testid="stMain"]');
                        if (!target || !scroller) return;
                        event.preventDefault();
                        const top = target.getBoundingClientRect().top
                          - scroller.getBoundingClientRect().top
                          + scroller.scrollTop - 12;
                        scroller.scrollTo({top: top, behavior:
                          window.matchMedia("(prefers-reduced-motion: reduce)").matches
                            ? "auto" : "smooth"});
                      });
                    }
                    </script>
                    """,
                    height=0,
                )
            st.markdown(
                "<ul class='el-hero-ticks'>"
                "<li>✓ Every answer cited</li>"
                "<li>✓ Checked before shown</li>"
                "<li>✓ Human review built in</li>"
                "</ul>",
                unsafe_allow_html=True,
            )
        with right:
            if yes_text:
                answer_html = (
                    "<p class='el-kicker'>Saved answer · cav_walk1</p>"
                    "<p class='el-verdict-word' style='font-size:clamp(32px,3vw,44px)'>Yes</p>"
                    f"<p>{html.escape(yes_text)}</p>"
                    f"<p class='el-clip-id'>{html.escape(span)} · EV-0001</p>"
                )
            else:
                answer_html = (
                    "<p class='el-kicker'>cav_walk1</p>"
                    "<p><strong>No saved answer yet</strong></p>"
                )
            st.markdown(
                "<div class='el-hero-window'>"
                "<p class='el-win-bar'><i class='el-dot el-dot-ok'></i>"
                "<i class='el-dot el-dot-warn'></i><i class='el-dot el-dot-bad'></i>"
                " Investigate</p>"
                f"{answer_html}"
                f"<img src='{HOME_START}' alt='cav_walk1, the frame saved at the start of EV-0001'>"
                "</div>",
                unsafe_allow_html=True,
            )

    icons = {
        "see": line_icon(
            "<path d='M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12'/>"
            "<circle cx='12' cy='12' r='3'/>"
        ),
        "decide": line_icon(
            "<path d='M9 11l3 3 8-8'/>"
            "<path d='M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11'/>"
        ),
        "answer": line_icon("<path d='M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z'/>"),
        "check": line_icon("<circle cx='12' cy='12' r='9'/><path d='M8 12l3 3 5-6'/>"),
    }
    steps = [
        ("see", "See", "The detector and tracker record people, bags and track IDs. They do not answer the question."),
        ("decide", "Decide", "Rules record a zone intrusion or a left-behind bag. A fall is not checked."),
        ("answer", "Answer", "The question is sent with the evidence file. The video is not sent."),
        ("check", "Check", "A citation is shown only when its ID and time exist in that file."),
    ]
    cards = []
    for index, (key, title, text) in enumerate(steps):
        cards.append(
            f"<article class='el-home-card' style='animation-delay:{index * 60}ms'>"
            f"{icons[key]}<h3>{title}</h3><p>{html.escape(text)}</p></article>"
        )
    st.markdown(
        "<section class='el-home-sec' id='el-how' style='animation-delay:60ms'>"
        "<h2 class='el-home-h2'>How it works</h2>"
        "<p class='el-home-sub'>Four steps. The model is only in the third.</p>"
        f"<div class='el-home-grid'>{''.join(cards)}</div></section>",
        unsafe_allow_html=True,
    )

    def verdict_card(kind: str, word: str, saved: dict | None, clip_id: str, question: str, body: str) -> str:
        css = {"yes": "el-vmini-yes", "no": "el-vmini-no", "abstain": "el-vmini-abstain"}[kind]
        mark = {"yes": "✓", "no": "–", "abstain": "?"}[kind]
        if saved is None:
            return (
                f"<article class='el-verdict-mini {css}'>"
                f"<p class='el-kicker'>Example</p>"
                f"<p class='el-verdict-word' style='font-size:clamp(32px,3vw,44px)'>{mark} {word}</p>"
                "<p>No saved answer of this kind is in the cache. This is not a result.</p>"
                "</article>"
            )
        return (
            f"<article class='el-verdict-mini {css}'>"
            f"<p class='el-kicker'>Saved answer · {html.escape(clip_id)}</p>"
            f"<p class='el-verdict-word' style='font-size:clamp(32px,3vw,44px)'>{mark} {word}</p>"
            f"<p>{html.escape(question)}</p>"
            f"<p>{html.escape(body)}</p></article>"
        )

    no_body = claim_text(no) or "The saved answer has no claim text."
    if abstain is None:
        abstain_body = ""
    else:
        plain = abstention_plain(evidence, ABSTAIN_QUESTION) if evidence else ""
        abstain_body = plain or "The saved answer abstained and made no claim."
    ask_cards = [
        verdict_card("yes", "Yes", yes, DEMO_CLIP, YES_QUESTION, yes_text or "The saved answer made no claim."),
        verdict_card("no", "No", no, "cav_walk2", NO_QUESTION, no_body),
        verdict_card("abstain", "Can't tell", abstain, DEMO_CLIP, ABSTAIN_QUESTION, abstain_body),
    ]
    st.markdown(
        "<section class='el-home-sec' style='animation-delay:120ms'>"
        "<h2 class='el-home-h2'>What you can ask</h2>"
        "<p class='el-home-sub'>Three outcomes. Each card below is a saved answer, or it is marked Example.</p>"
        f"<div class='el-home-grid'>{''.join(ask_cards)}</div></section>",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<section class='el-home-sec' style='animation-delay:180ms'>"
        "<h2 class='el-home-h2'>Proof, not promises</h2>"
        f"<p class='el-home-sub'>cav_walk1, event EV-0001. {html.escape(footer_text())}</p>"
        "<div class='el-home-grid'>"
        "<article class='el-home-card'><h3>Checked</h3>"
        "<p>✓ The saved yes cites a real event, EV-0001.</p>"
        f"<p>✓ The recorded time is {html.escape(span)}.</p>"
        f"<p>✓ Zone coverage on this clip is {html.escape(covered)}.</p>"
        "<p>✓ A citation is rejected when the ID or the time is not in the file.</p>"
        "</article>"
        "<article class='el-home-card'><h3>What was recorded</h3>"
        f"<p class='el-trace'>{html.escape(trace or 'No rule trace was saved for EV-0001.')}</p>"
        "<div class='el-home-grid'>"
        f"<img src='{HOME_START}' alt='EV-0001 start frame'>"
        f"<img src='{HOME_END}' alt='EV-0001 end frame'>"
        "<p>The peak frame was not saved for this event. These two frames are the ones in the evidence package.</p>"
        "</div></article></div></section>",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<section class='el-home-sec' style='animation-delay:240ms'>"
        "<h2 class='el-home-h2'>Live monitor</h2>"
        f"<p class='el-home-sub'>{html.escape(LIVE_LABEL)}</p>"
        "<div class='el-home-grid'>"
        "<article class='el-home-card'><p class='el-kicker'>Fast lane</p><h3>Provisional</h3>"
        "<p>Boxes on the live picture are a preview. They are not an answer.</p></article>"
        "<article class='el-home-card'><p class='el-kicker'>Answer lane</p><h3>Verified</h3>"
        f"<p>The recording is saved and processed. A question can be asked after that. {html.escape(AUTO_STOP_TEXT)}.</p>"
        "</article></div></section>",
        unsafe_allow_html=True,
    )

    limits = [
        ("Falls", FALL_NOTE),
        ("Very short entries", "An entry shorter than the 1.0 s dwell is not a zone event."),
        ("A bag on the floor", "A bag in the picture is not, by itself, a left-behind-bag event."),
        ("Modes A and C", "Only condition B is built. A and C are not implemented yet."),
    ]
    dashed = "".join(
        f"<article class='el-dash'><h3>{html.escape(title)}</h3><p>{html.escape(text)}</p></article>"
        for title, text in limits
    )
    st.markdown(
        "<section class='el-home-sec' style='animation-delay:300ms'>"
        "<h2 class='el-home-h2'>What it does not do yet</h2>"
        f"<div class='el-home-grid'>{dashed}</div>"
        f"<p class='el-home-sub' style='margin-top:24px'>We say it up front. {html.escape(footer_text())}</p>"
        "</section>",
        unsafe_allow_html=True,
    )

    with st.container(key="homeclose"):
        st.markdown(
            "<h2 class='el-hero-title' style='font-size:clamp(30px,2.6vw,42px)'>Open a clip, or record one.</h2>",
            unsafe_allow_html=True,
        )
        open_col, record_col, _spacer = st.columns([1, 1, 2])
        with open_col:
            if st.button("Open the app", key="home-open"):
                st.session_state.nav_screen = "Clip library"
                st.rerun()
        with record_col:
            if st.button("Record a clip", key="home-record"):
                st.session_state.nav_screen = "Analyse a new clip"
                st.rerun()
    st.markdown(
        "<p class='el-home-foot'>A CS3235 course project</p>"
        "<p class='el-home-foot'>Answers are for human review, not proof.</p>",
        unsafe_allow_html=True,
    )


def main() -> None:
    inject_css()
    apply_navigation()
    render_top_bar()
    page = st.session_state.page
    view = st.session_state.get("ui_view") or "simple"
    screen = SCREEN_OF.get(page, "Investigate")
    if st.query_params.get("page") != page:
        st.query_params["page"] = page
    if st.query_params.get("screen") != screen:
        st.query_params["screen"] = screen
    if st.query_params.get("view") != view:
        st.query_params["view"] = view
    manifest = load_manifest()
    if page == "library":
        page_library()
    elif page == "report":
        page_report()
    elif page == "analyse":
        page_analyse()
    elif page == "home":
        page_home()
    else:
        page_investigate(manifest)
    st.markdown(
        f"<div class='el-footer'>{html.escape(footer_text())}</div>",
        unsafe_allow_html=True,
    )


main()
