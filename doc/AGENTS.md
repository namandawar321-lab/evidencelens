# EvidenceLens — agent handoff

You are working on the prototype of a university course project (CS3235, RV
University). The four Python files in this repo were written in a separate
session and are already tested. Read this whole file before changing anything.

Cursor reads `AGENTS.md` automatically. If it doesn't pick it up, the user can
`@`-mention this file, or copy it to `.cursor/rules/evidencelens.mdc`.

---

## 1. What the system is

A reviewer asks a natural-language question about a recorded CCTV clip
("Did anyone enter the restricted area?"). The system answers **only** from
evidence extracted by computer vision and rules, **cites evidence IDs and
timestamps**, and **abstains** when the evidence cannot answer.

The research point of the project is that a video-LLM reading raw footage
hallucinates events and timestamps. So the design removes the LLM from
detection entirely and measures the difference.

```
OFFLINE (local RTX 4060 Laptop (8 GB))
clip → OpenCV decode → YOLO11s detect → ByteTrack → rule engine → evidence.json + keyframes

ONLINE (CPU only)
question + evidence.json → Gemini (JSON, temp 0) → validator → cited answer / abstention
```

Three experiment conditions, same prompt skeleton, schema and decoding, only
the input changes:

| | Input to the LLM |
|---|---|
| **A** | the raw video clip (baseline) |
| **B** | the evidence JSON only ← **this is what the prototype implements** |
| **C** | B plus a second verification pass |

---

## 2. Hard invariants — do not break these

These are not style preferences. The project's entire claim rests on them, and
a change here invalidates the experiment.

1. **The LLM never detects events.** Events come only from deterministic rules
   in `build_evidence.py`. Never ask the model to find, infer or judge an event.
2. **The LLM never computes a timestamp.** It may only copy `t_start` /
   `t_end` of items it cites. All times come from `t_s = frame_idx / fps_native`,
   computed in code.
3. **Every claim cites at least one evidence ID** (`EV-xxxx` or `TRK-n`) that
   exists in the evidence package.
4. **The validator is not advisory.** Schema → IDs exist → cited times inside
   the cited spans ±0.5 s. On failure: re-ask once, then abstain. Never show an
   unvalidated answer.
5. **Three distinct outcomes, never collapsed into one "unknown":**
   - `positive_evidence` — an event supports the answer
   - `verified_negative` — the relevant rule covered the whole clip and found nothing
   - `insufficient_evidence` — abstention
   `verified_negative` requires full coverage for that rule. If
   `coverage[rule]` is empty or partial, the system must abstain instead.
6. **Requirement IDs are stable.** `FR-1..FR-12`, `NFR-1..NFR-13`, `M1..M13` are
   referenced by the report and the viva. Never renumber them. New work gets a
   new ID; it does not reuse an old one.
7. **No identification or inference about people.** No face recognition,
   re-identification, demographics, intent, guilt, emotion, injury or medical
   state. Every output carries `human_review_required = true`, and the report
   carries "for human review — not proof".
8. **Never present example output as a real result.** Illustrative data must be
   labelled as illustrative, in code comments, docs and the UI alike.
9. **Thresholds are design assumptions, not tuned values.** Changing one means
   changing `THRESHOLDS` in `build_evidence.py` and re-running `test_rules.py`.
   Thresholds get frozen before the test run; after that, do not touch them.

---

## 3. The files

The requirements for the build are in `doc/REQUIREMENTS_FOR_CURSOR.md`.

| File | Role | Covers |
|---|---|---|
| `build_evidence.py` | offline stage: detection, tracking, rules, `evidence.json`, keyframes | FR-2, FR-3, FR-5 |
| `ask.py` | online stage: prompt, Gemini call, citation validator, rendering | FR-6, FR-7, FR-8 |
| `draw_zone.py` | click a zone polygon on the first frame, save as JSON | FR-4 |
| `test_rules.py` | 21 synthetic checks; no video, GPU or API key needed | — |
| `README.md` | setup and run commands | — |

### Entry points

```bash
python draw_zone.py data/clips/<clip>.mp4 --zone-id Z1 --label "restricted door"
python build_evidence.py data/clips/<clip>.mp4 --zone data/zones/<clip>.json --short-clip-mode
python ask.py <clip_stem> "Was an object left unattended?"
python test_rules.py
```

### Key internals

- `build_evidence.py` → `THRESHOLDS` dict (all tunables in one place),
  `run_tracking()`, `rule_zone_intrusion()`, `rule_unattended_object()`,
  `build()` which assembles the evidence dict.
- `ask.py` → `SYSTEM_RULES` (the prompt skeleton — see §5 before editing),
  `build_prompt()`, `call_gemini()`, `validate()`, `ask()`, `render()`.
- `Detection` exposes `centre`, `foot_point`, `height`, `diagonal`.
  `Track` exposes `t_start`, `t_end`, `mean_conf`, `at(frame_idx)`, `fragmented()`.

### Implemented rules

- **Zone intrusion.** Person foot point (bottom-centre of the box) inside the
  polygon ≥ 1.0 s; ends after ≥ 1.0 s outside; same-track events < 2 s apart
  are merged; detection confidence ≥ 0.4.
- **Unattended object.** Bag static (centre moves < 5% of its box diagonal over
  3 s); owner = the person track nearest before it became static; unattended
  candidate when the owner is > 1.5 × their box height away or their track is
  lost; fires after T = 30 s (10 s with `--short-clip-mode`); re-attended if the
  owner returns within 1.0 × box height. **Ambiguous ownership** (another
  person within 20% of the same distance) produces an event with
  `owner_track_id: null` and `status: "needs_review"`, never a claimed owner.
  Distances are in owner-height units because the cameras are uncalibrated.
- **Fall — not implemented.** `coverage.fall` is `[]`, so the system must
  abstain on fall questions.

### evidence.json shape

`schema_version: "2.0-poc"`, then `video` (ids, licence, consent_basis, fps,
sha256), `zones`, `tracks`, `events`, `coverage` (time ranges each rule actually
processed), `provenance` (detector, weights, tracker, imgsz, stride, commit,
run time), `limits`. Each event: `event_id`, `type`, `t_start`, `t_end`,
`track_ids`, `rule_id`, `rule_version`, `thresholds`, `rule_trace`,
`confidence`, `status`, `supporting_frames`.

---

## 4. Current state

- All four scripts parse; `test_rules.py` passes 21/21.
- **Never run against real footage.** No clip has been processed yet, so
  detection quality, tracking stability and rule behaviour on real video are
  entirely unverified. Treat anything about real-world performance as unknown.
- The riskiest unknown: whether ByteTrack holds a stable ID on a small bag in
  low-resolution footage. If it doesn't, the unattended-object rule fails and
  the fallback is `--imgsz 1280`, then BoT-SORT.
- `MODEL_ID` in `ask.py` defaults to `gemini-3.8-flash` and is a placeholder.
  Override with the `EVIDENCELENS_MODEL` environment variable. The exact ID is
  being confirmed; do not hard-code a different one.

---

## 5. Changes that need the user's explicit approval first

Ask before doing any of these. They affect the experiment's validity, not just
the code.

- **Editing `SYSTEM_RULES` in `ask.py`.** The prompt skeleton must stay
  identical across conditions A, B and C — only the input may differ. An
  improvement to B's prompt silently confounds the comparison.
- **Adding few-shot examples.** Explicitly excluded: it risks test leakage.
- **Changing any value in `THRESHOLDS`.**
- **Loosening the validator**, including widening the ±0.5 s tolerance.
- **Adding a framework** (LangChain, an agent framework, a vector DB). The
  design is deliberately a single LLM call plus a validator loop.
- **Changing the schema field names** in `evidence.json`.

---

## 6. Work queue, in order

Do one item, run `test_rules.py`, and stop for review. Do not batch these.

1. **Run the pipeline on a real clip** and report what actually happened: how
   many tracks, whether IDs stayed stable, whether the rules fired, and the
   RTX 4060 Laptop (8 GB) timing (needed for NFR-2's real-time factor ≤ 0.5).
2. **Add `±3 s` event clips** next to the keyframes. FR-5 requires both; only
   keyframes exist now. Write them as MP4 beside `frames/`, and reference them
   from `event.clip_path`.
3. **Fall rule** (FR-5). Within 1.0 s the torso angle goes from < 30° to > 60°
   from vertical (YOLO11s-pose), **or** the box aspect ratio from < 0.8 to
   > 1.2; the hip descends > 0.25 × the initial box height; and the person stays
   low for ≥ 2.0 s. If torso keypoint confidence < 0.3, use the box rule and
   mark visibility `partial`. Sitting, bending and deliberate lying are the
   expected false positives — add them as synthetic hard negatives in
   `test_rules.py` in the same commit. Then set `coverage.fall` to the processed
   range. **No injury or medical inference.**
4. **Streamlit Investigate screen** (FR-11): question box, answer card
   (decision, abstained, reason), claims with clickable evidence IDs, an
   evidence panel showing keyframes, the clip and the rule trace, confirm and
   reject buttons, and a "for human review — not proof" banner. Desktop only,
   minimum width 1280 px. Show the full validated response, not a token stream,
   because the JSON must be validated before it is displayed.
5. **Conditions A and C** in an offline evaluation harness (FR-10), logging
   output, tokens, cost and latency per question. Condition A sends the raw clip
   to Gemini with the *same* prompt skeleton and schema.

---

## 7. Conventions

- Python 3.11, standard library plus the four packages in `requirements.txt`.
  Ask before adding a dependency.
- No network calls in `build_evidence.py`. It is offline by design.
- Keep all tunables in `THRESHOLDS`; no magic numbers in rule bodies.
- Every new rule writes a human-readable `rule_trace` saying *why* it fired,
  with the numbers in it. A reviewer reads this string in the UI.
- Add a synthetic scenario to `test_rules.py` for every rule change, in the same
  commit. The tests must run without video, GPU or API key.
- `data/` stays out of Git (clips, evidence, weights).
- Secrets come from environment variables only. Never commit an API key.
- The repo is public and uses Ultralytics (AGPL-3.0), so any code copied in must
  have a compatible licence. Check before pasting from another repo.

---

## 8. Reporting back

The user relays messages between you and the assistant that wrote this code.
When you finish an item, give the user a short block they can paste back:

```
DONE: <item number and name>
CHANGED: <files>
TESTS: <n>/<n> passing  (or: which ones fail and why)
OBSERVED: <what actually happened on real data — numbers, not impressions>
BLOCKED / NEEDS DECISION: <anything from §5, or an assumption you had to make>
```

Be specific and mark assumptions as assumptions. Report real measurements as
measurements and guesses as guesses — this project is graded partly on not
overclaiming.
