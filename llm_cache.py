"""Cache for condition-B answers.

The key is a sha256 of the canonical evidence JSON, the normalised question,
the model ID, a hash of SYSTEM_RULES, condition B, and the decoding parameters.
api_error results are not stored. This module does not edit rules or the validator.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from ask import MODEL_ID, SYSTEM_RULES, ask

ROOT = Path(__file__).resolve().parent
EVIDENCE_ROOT = ROOT / "data" / "evidence"
CACHE_ROOT = ROOT / "data" / "llm_cache"

CONDITION = "B"
DECODING = {"temperature": 0, "response_mime_type": "application/json"}


def normalise_question(question: str) -> str:
    """Lowercase, collapse whitespace, and remove one trailing question mark."""
    text = " ".join(str(question).lower().split())
    if text.endswith("?"):
        text = text[:-1].rstrip()
    return text


def evidence_for_key(evidence: dict) -> dict:
    """Drop presentation-only clip_path values so a saved extract does not change the key."""
    cloned = json.loads(json.dumps(evidence))
    for event in cloned.get("events") or []:
        if isinstance(event, dict):
            event.pop("clip_path", None)
    return cloned


def canonical_evidence(evidence: dict) -> str:
    return json.dumps(
        evidence_for_key(evidence),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(
    evidence: dict,
    question: str,
    model_id: str = MODEL_ID,
    system_rules: str = SYSTEM_RULES,
    condition: str = CONDITION,
    decoding: dict | None = None,
) -> str:
    payload = {
        "evidence": canonical_evidence(evidence),
        "question": normalise_question(question),
        "model": model_id,
        "system_rules_sha256": sha256_text(system_rules),
        "condition": condition,
        "decoding": DECODING if decoding is None else decoding,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_text(blob)


def _load_evidence(clip: str, evidence_root: Path) -> dict:
    path = evidence_root / clip / "evidence.json"
    if not path.is_file():
        raise SystemExit(f"no evidence package at {path} - run build_evidence.py first")
    return json.loads(path.read_text(encoding="utf-8"))


def lookup_cached(
    clip: str,
    question: str,
    evidence_root: Path | None = None,
    cache_root: Path | None = None,
) -> dict | None:
    """Return a cached result, or None. Does not call the model."""
    evidence_root = EVIDENCE_ROOT if evidence_root is None else evidence_root
    cache_root = CACHE_ROOT if cache_root is None else cache_root
    evidence = _load_evidence(clip, evidence_root)
    key = cache_key(evidence, question)
    path = cache_root / f"{key}.json"
    if not path.is_file():
        return None
    entry = json.loads(path.read_text(encoding="utf-8"))
    return {
        "answer": entry["answer"],
        "source": "cached",
        "cached_at": entry.get("timestamp"),
        "key": key,
    }


def ask_cached(
    clip: str,
    question: str,
    evidence_root: Path | None = None,
    cache_root: Path | None = None,
) -> dict:
    """Return the validated answer plus source "cached" or "live".

    A live api_error is returned and not written to the cache.
    """
    evidence_root = EVIDENCE_ROOT if evidence_root is None else evidence_root
    cache_root = CACHE_ROOT if cache_root is None else cache_root
    evidence = _load_evidence(clip, evidence_root)
    key = cache_key(evidence, question)
    path = cache_root / f"{key}.json"
    if path.is_file():
        entry = json.loads(path.read_text(encoding="utf-8"))
        return {
            "answer": entry["answer"],
            "source": "cached",
            "cached_at": entry.get("timestamp"),
            "key": key,
        }

    answer = ask(clip, question, evidence_root, False)
    result = {"answer": answer, "source": "live", "cached_at": None, "key": key}
    if answer.get("status") == "api_error":
        return result

    cache_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    entry = {
        "answer": answer,
        "validation_status": answer.get("_validated"),
        "model": answer.get("_model") or MODEL_ID,
        "token_counts": answer.get("_token_counts"),
        "latency_ms": answer.get("_latency_ms"),
        "timestamp": timestamp,
        "clip_id": clip,
        "question": question,
        "condition": CONDITION,
        "key": key,
    }
    path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return result
