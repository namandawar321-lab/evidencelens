"""Synthetic checks for the LLM answer cache. No video, GPU or API key.

    python test_llm_cache.py
"""

from __future__ import annotations

import json
from pathlib import Path

import llm_cache
from llm_cache import cache_key

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((PASS if condition else FAIL, name, detail))


EVIDENCE = {
    "video": {"video_id": "synthetic", "duration_s": 10.0},
    "events": [{"event_id": "EV-0001", "t_start": 1.0, "t_end": 2.0}],
    "coverage": {"zone_intrusion": [[0.0, 10.0]]},
}
RULES_A = "rule text A"
MODEL = "test-model"


def test_same_input_same_key() -> None:
    left = cache_key(EVIDENCE, "Did anyone enter the restricted zone?", MODEL, RULES_A)
    right = cache_key(EVIDENCE, "  did   anyone enter the restricted zone?  ", MODEL, RULES_A)
    check("same input, same key", left == right and len(left) == 64, left[:12])


def test_evidence_change() -> None:
    changed = json.loads(json.dumps(EVIDENCE))
    changed["events"][0]["t_end"] = 3.0
    left = cache_key(EVIDENCE, "Did anyone enter?", MODEL, RULES_A)
    right = cache_key(changed, "Did anyone enter?", MODEL, RULES_A)
    check("evidence change changes the key", left != right)


def test_question_change() -> None:
    left = cache_key(EVIDENCE, "Did anyone enter the restricted zone?", MODEL, RULES_A)
    right = cache_key(EVIDENCE, "Did a person fall?", MODEL, RULES_A)
    check("question change changes the key", left != right)


def test_system_rules_change() -> None:
    left = cache_key(EVIDENCE, "Did anyone enter?", MODEL, RULES_A)
    right = cache_key(EVIDENCE, "Did anyone enter?", MODEL, RULES_A + " extra")
    check("SYSTEM_RULES change changes the key", left != right)
    from ask import SYSTEM_RULES
    current = cache_key(EVIDENCE, "Did anyone enter?", MODEL, SYSTEM_RULES)
    edited = cache_key(EVIDENCE, "Did anyone enter?", MODEL, SYSTEM_RULES + " extra")
    check("imported SYSTEM_RULES change changes the key", current != edited)


def _write_evidence(root: Path) -> None:
    folder = root / "clip" 
    folder.mkdir(parents=True)
    (folder / "evidence.json").write_text(json.dumps(EVIDENCE), encoding="utf-8")


def test_api_error_never_cached(tmp: Path) -> None:
    evidence_root = tmp / "evidence"
    cache_root = tmp / "cache"
    _write_evidence(evidence_root)
    calls = {"n": 0}

    def fake_ask(clip: str, question: str, root: Path, dry_run: bool) -> dict:
        calls["n"] += 1
        return {
            "status": "api_error",
            "decision": None,
            "abstained": False,
            "reason": None,
            "_validated": False,
            "_model": MODEL,
            "_latency_ms": 12,
            "_token_counts": {"input": None, "output": None, "total": None},
        }

    original = llm_cache.ask
    llm_cache.ask = fake_ask
    try:
        first = llm_cache.ask_cached("clip", "Did anyone enter?", evidence_root, cache_root)
        second = llm_cache.ask_cached("clip", "Did anyone enter?", evidence_root, cache_root)
    finally:
        llm_cache.ask = original
    files = list(cache_root.glob("*.json")) if cache_root.exists() else []
    check(
        "api_error is never cached",
        first["source"] == "live"
        and second["source"] == "live"
        and calls["n"] == 2
        and files == [],
        f"calls={calls['n']} files={len(files)}",
    )


def test_success_is_cached(tmp: Path) -> None:
    evidence_root = tmp / "evidence"
    cache_root = tmp / "cache"
    _write_evidence(evidence_root)
    calls = {"n": 0}

    def fake_ask(clip: str, question: str, root: Path, dry_run: bool) -> dict:
        calls["n"] += 1
        return {
            "decision": "cannot_determine",
            "abstained": True,
            "reason": "insufficient_evidence",
            "claims": [],
            "human_review_required": True,
            "_validated": True,
            "_model": MODEL,
            "_latency_ms": 20,
            "_token_counts": {"input": 3, "output": 4, "total": 7},
        }

    original = llm_cache.ask
    llm_cache.ask = fake_ask
    try:
        first = llm_cache.ask_cached("clip", "Did a person fall?", evidence_root, cache_root)
        second = llm_cache.ask_cached("clip", "Did a person fall?", evidence_root, cache_root)
    finally:
        llm_cache.ask = original
    files = list(cache_root.glob("*.json"))
    stored = json.loads(files[0].read_text(encoding="utf-8")) if files else {}
    check(
        "a validated answer is cached and the repeat is served from cache",
        first["source"] == "live"
        and second["source"] == "cached"
        and calls["n"] == 1
        and len(files) == 1
        and stored.get("validation_status") is True
        and stored.get("token_counts") == {"input": 3, "output": 4, "total": 7}
        and stored.get("model") == MODEL
        and second.get("cached_at") == stored.get("timestamp"),
        f"calls={calls['n']} files={len(files)}",
    )


def main() -> None:
    import tempfile

    test_same_input_same_key()
    test_evidence_change()
    test_question_change()
    test_system_rules_change()
    with tempfile.TemporaryDirectory() as tmp:
        test_api_error_never_cached(Path(tmp) / "err")
    with tempfile.TemporaryDirectory() as tmp:
        test_success_is_cached(Path(tmp) / "ok")
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
