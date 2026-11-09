# EvidenceLens: requirements for the build agent

Condensed from the team's Requirements Document v0.4 (23-10-2026). This file drives the code. The full document stays the source of truth for hosting, risks, timeline and literature, none of which matter for writing code. Read `AGENTS.md` first: its invariants and approval rules still apply.

Last status update: 29-10-2026.

## 1. What the system is
A reviewer asks a natural-language question about a recorded CCTV clip. Computer vision and explicit rules find the events and write `evidence.json`. Gemini answers only from that file, cites evidence IDs and times, and abstains when the evidence cannot answer. A runtime validator checks every answer. The LLM never detects events and never computes timestamps. Every output is "for human review, not proof".

## 2. Scope
In scope: recorded clips (<= 2 min, <= 720p, one fixed camera); person and bag detection; tracking; three event rules (zone intrusion, fall, unattended object); evidence package (JSON, keyframes, +/-3 s event clips); grounded QA with abstention; incident report; reviewer confirm/reject; A/B/C comparison; later a public cloud demo with precomputed evidence.

Out of scope: live or streaming video, multi-camera, re-identification, face recognition, identifying people, demographics, inferring intent/guilt/medical state, alerts or enforcement, training or fine-tuning, OCR, dashboards, CI/CD, accounts, mobile UI.

Pending scope question (needs the user's decision, do not build unasked): "record from webcam, then process the recorded clip" is within "recorded clips". True real-time streaming is NOT.

## 3. Functional requirements and status
| ID | Requirement (short) | Priority | Status |
|---|---|---|---|
| FR-1 | Ingest MP4/AVI; record fps, duration, resolution, SHA-256, licence/consent; reject a clip with no licence/consent record | Must | Partly: metadata recorded; no rejection yet |
| FR-2 | Detect persons and bags (backpack, handbag, suitcase) at configurable rate | Must | Done (YOLO11s, stride 2). AP50 check (M4) not done |
| FR-3 | Track IDs, flag fragmented tracks | Must | Done (ByteTrack) |
| FR-4 | Named zone polygons per camera, versioned | Must | Tool exists (`draw_zone.py`); not yet used on a real clip |
| FR-5 | Emit zone_intrusion, fall, unattended_object events with times, track IDs, rule ID/version, thresholds, rule trace, confidence, >= 3 keyframes, +/-3 s clip | Must | unattended_object done; zone_intrusion tested synthetically only; fall NOT built; +/-3 s clip file NOT written |
| FR-6 | Answer from the evidence package only; decision, abstained, reason, claims citing IDs and time ranges | Must | Done (condition B) |
| FR-7 | Abstain with insufficient_evidence when evidence or coverage is insufficient; verified_negative only when the relevant rule covered the whole clip | Must | Done, tightened (see section 9) |
| FR-8 | Runtime validator: schema, IDs exist, cited times inside spans +/-0.5 s; re-ask once, then abstain | Must | Done |
| FR-9 | Incident report per clip, marked "for human review, not proof" | Must | Done in UI (Markdown download) |
| FR-10 | Run conditions A, B, C on the same questions, same prompt skeleton, schema and decoding; log outputs, tokens, cost, latency | Must | Only B |
| FR-11 | UI opens cited frames and clip per claim; confirm or reject | Should | Done in UI |
| FR-12 | Count unique person tracks entering a zone | Could | Not started |

## 4. Event definitions (thresholds are design assumptions; tuned on a development split, then frozen. Do not tune on one clip.)
- **Zone intrusion.** Foot point (bottom-centre of the person box) inside the polygon for >= 1.0 s; event ends after >= 1.0 s outside; same-track events < 2 s apart are merged; detection confidence >= 0.4.
- **Fall.** Within 1.0 s the torso angle goes from < 30 deg to > 60 deg from vertical (pose), or the box aspect ratio from < 0.8 to > 1.2; hip descends by > 0.25 x the initial box height; person stays low or horizontal >= 2.0 s. If torso keypoint confidence < 0.3, use the box rule and mark visibility "partial". Sitting, bending and deliberate lying are expected false positives and must be hard negatives. No injury or medical inference.
- **Unattended object** (PETS 2006 logic in owner-height units). Static = box centre moves < 5% of its diagonal over 3 s. Owner = the person track nearest or overlapping the object before it became static (current code: nearest within owner_window_s = 2.0 s). Unattended candidate when the owner is > 1.5 x their box height away or their track is lost. Fires after T = 30 s (10 s in declared short-clip mode). Attended again if the owner returns within 1.0 x box height. A person and a bag in the same frame never establish abandonment on their own; abstain (status needs_review, owner null) if the owner is uncertain.

## 5. Evidence package (schema "2.0-poc" in code; v2.0 in the doc)
Sections: `video` (video_id, camera_id, source_dataset, licence, consent_basis, fps_native, fps_processed, frame_count, duration_s, resolution, sha256), `zones` (zone_id, camera_id, polygon in pixel coordinates of the original frame, label, version), `tracks` (track_id, class, t_start, t_end, n_frames, mean_conf, visibility, fragmented), `events` (event_id, type, t_start, t_end, track_ids, zone_id / object_track_id / owner_track_id, rule_id, rule_version, thresholds, rule_trace, confidence, supporting_frames, clip_path, status in candidate | confirmed_by_rule | needs_review), `provenance`, `coverage` (time ranges each rule actually processed), `limits`.
t_s = frame_idx / fps_native, computed by code only.

Fields added during the build (keep them): `class_votes` per track (majority label), `tracks_omitted_short`, `negative_eligible` per rule, `detector_summary`.
`negative_eligible`: unattended_object needs coverage of the whole clip AND >= 1 bag track; zone_intrusion needs a zone, whole-clip coverage AND >= 1 person track; fall is never eligible until implemented.

## 6. LLM answer contract and validator
Output JSON: `decision` (yes | no | cannot_determine), `abstained`, `reason` (positive_evidence | verified_negative | insufficient_evidence), `claims[]` each with `text`, `cited_ids[]` (EV-, TRK-, COV-<rule>), `cited_time_range`, and `human_review_required` = true.
The model may only copy t_start / t_end of cited items. Validator rules: schema complete; every cited ID exists; cited times inside cited spans +/-0.5 s; "yes" must cite an EV- event with status confirmed_by_rule (needs_review never counts); "no" must cite COV-<rule> with negative_eligible true; an abstention carries no claims. Failure: re-ask once with the problems listed, then abstain. API failures (404, quota, 503 after retries) are status "api_error": not an abstention, decision null. Intent, identity, emotion, injury and medical state are never answered.
Cache (planned, per doc): key = sha256(evidence JSON) + normalised question + model ID + prompt version + decoding parameters + condition. Cached answers are labelled "cached".

## 7. Conditions (same prompt skeleton, schema, decoding; only the input differs)
A = raw video clip (File API, 1 FPS), evaluation harness only, no evidence IDs so no citation validator; B = evidence JSON only (built); C = B plus a second verification pass, optionally up to 3 keyframes (design decision due 16-11).

## 8. UI specification (Streamlit, desktop >= 1280 px, no extra component library, native components plus small custom CSS)
Display the full validated response, never a token stream. Spinner with elapsed seconds while waiting. WCAG AA contrast (>= 4.5:1). Every status has a text label as well as colour. Keyframes have text alternatives (event type and timestamp). Confirmed/rejected shown with text.

Times are shown as mm:ss.s (for example 00:18.2).

**Screen 1: Clip library.** Clip list with licence/consent badge; metadata (fps, duration, resolution); first frame with zone polygons; processing status. A clip without an evidence package shows its processing status and questions are disabled.

**Screen 2: Investigate (main).** Layout from the draft wireframe:
- Header bar: "EvidenceLens   Clip: <id> (<duration>, <licence>)" on the left; Mode selector A / B / C on the right (B selected; A and C disabled until built).
- Left column: question text box with an "Ask" button; sample-question chips below it ("Was an object left?", "Did a person fall?", "Before 00:30?"); the Answer card; an amber "For human review. Not proof." banner; a distinct dashed "Abstention card" ("Cannot determine from evidence: <reason>").
- Answer card: line "decision: yes   abstained: no   reason: positive_evidence", then the claim text, then clickable chips for each cited ID (EV-0003, TRK-7) and the cited time range (00:18.2 to 00:27.6).
- Right column, "Evidence for EV-0003": three keyframes with timestamps under each; a video player for the +/-3 s clip; a rule box (rule id and version, dwell and threshold, confidence threshold, which point was inside which zone and the track); Confirm and Reject buttons.
- Errors: LLM timeout or failure shows a message and a Retry button. Cached answers are labelled "cached". Questions with no events show "no event found by the rules" ONLY when coverage is the full clip, otherwise "coverage incomplete".

**Screen 3: Incident report.** Amber banner "For human review. Not proof.  Clip: <id>  Generated from evidence package v2.0". Event table with columns Event, Type, Time, Conf., Status. A rule that ran over the whole clip and found nothing appears as a row such as "none | fall (rule ran) | full clip covered | verified_negative"; if the rule did not run or coverage is partial, say so instead. Supporting frames (click to open the clip), labelled for example "EV-0003 start / peak / EV-0005 end". A limits line ("single camera; no identification of people; rule thresholds are design assumptions"). A "Download report" button.

User flow: Clip library -> Investigate -> answer or abstention card -> click a citation to open keyframes, the +/-3 s clip and the rule trace -> confirm or reject -> Incident report -> download. Citations and rule traces are always one click from the claim.

## 9. Decisions that differ from the v0.4 document (do not revert)
- Model ID is pinned to `gemini-3.6-flash` (doc said gemini-3.8-flash, which was not callable). Free tier is 20 requests/day per project.
- GPU is an RTX 4060 Laptop (8 GB), not a 4070.
- FR-7 tightened: a verified_negative needs the relevant rule to have covered the whole clip AND the detector to have produced at least one track of that rule's object class (`negative_eligible`, `COV-<rule>` citation).
- Track labels use a majority vote; tracks < 5 frames are omitted unless cited, and the count is recorded.
- Owner selection uses owner_window_s = 2.0 s and distance to the bag box at the moment it became static; needs_review events cannot support "yes".
- CAVIAR LeftBag was rejected (bag never detected). CAVIAR is CC BY-SA with attribution: "Data from the EC Funded CAVIAR project/IST 2001 37540, http://homepages.inf.ed.ac.uk/rbf/CAVIAR/". Keep CAVIAR clips local until terms are confirmed for any public demo.
- Sampling is stride 2 on the native frame rate; the doc says 10 FPS default (15 for fall). Align or document when thresholds are frozen.

## 10. Metrics (names only; evaluation is a later stage)
M1 event F1; M2 false alarms per hour; M3 onset error; M4 detection AP50; M5 tracking quality; M6 unsupported-claim rate (positive and negative reported separately); M7 citation validity and support (first-pass validity >= 98%); M8 coverage and abstention; M9 answer accuracy; M10 efficiency (RTF <= 0.5, p95 query latency <= 15 s); M11 cost (<= Rs 1,000 total); M12 usability; M13 out-of-scope handling.

## 11. Working rules for this build
- Report real measurements as measurements and guesses as guesses.
- Never present example or saved output as a live result; label replays and cached answers.
- Do not change a threshold, SYSTEM_RULES, the validator tolerance or schema field names without the user's explicit approval (see AGENTS.md section 5).
- Each change that affects a rule needs a synthetic scenario in `test_rules.py` and a passing run.
- Finish every task with the AGENTS.md section 8 report block.
