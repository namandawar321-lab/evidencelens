# EvidenceLens: UI build spec for Cursor

Attach the six reference images with this file: `ui_product_home.png`, `ui_pg_library.png`, `ui_pg_investigate_simple.png`, `ui_pg_investigate_technical.png`, `ui_pg_report.png`, `ui_pg_analyse.png`. They show the layout, colours, spacing and components to match. Text and data in the images are placeholders; always use the real data from the app.

## 0. Rules (read first, do not break)

- This is a look-and-feel change only. Do NOT edit: the rules, `THRESHOLDS`, `SYSTEM_RULES`, `validate()`, the evidence schema, `build_evidence.py` logic, `llm_cache.py` keys, or any detector or tracker code. Do not change answers, cache behaviour or tests' expected values.
- All existing behaviour must keep working: Ask box, chips, cached/live label, validator checklist, abstention card, coverage panel for COV- citations, the app-written caveat for "no", api_error shown separately and never cached, annotated video, timeline, evidence panel, confirm/reject, grouped library, Analyse (record, upload, draw zone, Live monitor, Stop button), URL state restore.
- The existing test files must pass unchanged: `test_rules.py`, `test_llm_cache.py`, `test_record_clip.py`, `test_live_monitor.py`. Run them after each phase and report the counts.
- Never print or read `.env`. Do not add network calls other than what exists. The app must still work offline for the demo (see fonts, section 3).
- Honesty text must stay on screen exactly as described: "For human review · not proof", "Live preview is provisional. Evidence and answers come from the recorded session. The language model is not in the live loop.", A and C shown disabled as "not implemented yet". No accuracy numbers, no fake logos or testimonials anywhere (including Home).
- Desktop only, minimum width 1280 px. It must be fluid between 1280 and 1920 px (see section 4). Mobile is out of scope.
- Work in two phases (section 8). Stop after each phase, run tests, take screenshots, and report. Total time limit: 90 minutes. If something is not possible in Streamlit, use the nearest approximation and list it in the report. Do not fake it.

## 1. Design tokens

Put these in one place (a `ui/theme.py` module and one injected CSS string). Never hard-code colours elsewhere.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#f4f6fb` | page background |
| `--card` | `#ffffff` | cards |
| `--tint` | `#e8eefe` | page header band, soft fills, timeline track |
| `--line` | `#dfe5f1` | borders |
| `--ink` | `#0e1a3a` | main text |
| `--mute` | `#5a6785` | secondary text |
| `--brand` | `#2b5cff` | primary buttons, active nav, links, hero background |
| `--brand-dark` | `#1f45cc` | button hover |
| `--coral` | `#ff6b4a` | Live monitor button, event tag on video, hero call to action |
| `--ok` / `--okbg` | `#12a15a` / `#dff5e9` | Yes, passed checks, confirmed |
| `--info` / `--infobg` | `#2b5cff` / `#e3eaff` | No / no event found, cited pills |
| `--warn` / `--warnbg` | `#9a5b00` / `#ffefc9` | Can't tell, human review chip |
| `--bad` | `#d93a3a` | Reject, REC dot, errors |
| `--code` | `#e8eefe` | rule trace background |

Rules: flat colours only, no gradients anywhere. The hero and closing banner on Home use `--brand` with two flat circles in a slightly lighter blue (`#3d6bff`) and a slightly darker blue (`#2450e6`). Colour is never the only signal: always icon + word.

Shape: card radius 22 to 26 px, buttons 12 px, chips pill (999 px), verdict badge a circle. Borders 1 px `--line`. Soft shadow only on raised cards: `0 10px 30px rgba(43,92,255,.08)`.

Type: headings and body `Plus Jakarta Sans` (500, 600, 700, 800), IDs, times and rule traces `JetBrains Mono` (500, 600). Fluid sizes with clamp:
- Home hero title `clamp(44px, 4.2vw, 68px)`, weight 800, letter-spacing -0.035em, line-height 1.05
- Page title `clamp(30px, 2.6vw, 42px)`, weight 800
- Verdict word `clamp(40px, 3.4vw, 56px)`, weight 800
- Body 15 to 16 px, labels 12.5 to 13 px uppercase with letter-spacing .09em

## 2. Streamlit setup

- First check the installed Streamlit version. Use the newest APIs it has; fall back where noted.
- `st.set_page_config(page_title="EvidenceLens", layout="wide", initial_sidebar_state="collapsed")`. Remove the old sidebar radio navigation completely.
- `.streamlit/config.toml`: `[theme] base="light"`, `primaryColor="#2b5cff"`, `backgroundColor="#f4f6fb"`, `secondaryBackgroundColor="#e8eefe"`, `textColor="#0e1a3a"`, `font="sans serif"`; `[client] toolbarMode="minimal"`; `[server] enableStaticServing=true` (for local fonts).
- Inject one global CSS block at the top of every page (`st.markdown(css, unsafe_allow_html=True)` or `st.html`). In it hide Streamlit chrome (`header[data-testid="stHeader"]`, `footer`, `#MainMenu`, the sidebar and its toggle), remove default top padding, and set `.block-container{max-width:1440px;padding:0 clamp(16px,5vw,72px) 60px}`.
- Pages and routing: Home, Library, Investigate, Report, Analyse. If `st.navigation(position="top")` exists use it and style it; otherwise build the top bar yourself with HTML plus `st.button` or `st.page_link` and keep the current page in `st.session_state` and `st.query_params`. Clicking a nav item must NOT reload the whole app or lose session state. A browser refresh must restore page, clip, question and Simple/Technical choice from the URL (this already works for clip and question; keep it and add `view=simple|technical` and `page=`).
- Remount trick for animations: Streamlit only replays CSS animations on newly created DOM nodes. Give each answer container a changing `key` (for example a hash of clip + question + decision) and wrap content in an element whose class carries the animation, so a new answer replays its entrance animation and an unchanged rerun does not.

## 3. Fonts (offline-safe)

Self-host Plus Jakarta Sans and JetBrains Mono (both SIL Open Font Licence) as `.woff2` in `static/fonts/`, load them with `@font-face` pointing at `/app/static/fonts/...`, with `font-display: swap` and system-ui fallbacks. Add both fonts to `licence_log.csv`. The demo must look right with no internet.

## 4. Fluid layout rules

- Page container max-width 1440 px, side padding `clamp(16px, 5vw, 72px)`.
- Use CSS grid with `auto-fit` and `minmax`, not fixed pixel columns. Two-column pages use `grid-template-columns: minmax(0,5fr) minmax(0,7fr)` and collapse to one column under 1100 px.
- Library grid: `repeat(auto-fill, minmax(300px, 1fr))`.
- Video: `aspect-ratio: 4/3; width:100%; max-height: 70vh`. Never fixed width in px.
- Spacing scale: 4, 8, 12, 16, 24, 32, 48, 72. Gaps between cards 24 px.
- Images use `object-fit: cover`. Nothing may overflow horizontally at 1280 px.

## 5. Shared components (build once, reuse)

1. **Top bar:** white, 76 px, 1 px bottom border. Logo (blue rounded square with search icon) + "EvidenceLens", nav pills (active = `--tint` background, `--brand` text, bold), right side: Simple/Technical switch (Investigate only) and the coral **Live monitor** button with a pulsing white dot. Live monitor opens a small popover explaining the two lanes (fast lane provisional, answer lane verified, language model never in the live loop, auto-stop at 100 s).
2. **Page header band:** `--tint` background, small breadcrumb, page title, one-line subtitle.
3. **Card:** white, radius 24, 1 px border, hover lifts 3 px.
4. **Chip / pill:** status chips (Evidence ready = green, No events = amber, source = grey, event count = blue). Citation pills are buttons in mono font; clicking a pill selects that event and seeks the video.
5. **Verdict block:** round badge (✓ green for Yes, – blue for No, ? amber for Can't tell) + big word + one sentence + chips. The background tint matches the verdict (`--okbg`, `--infobg`, `--warnbg`).
6. **Stat card:** small uppercase label, big number, one-line caption.
7. **Stepper:** numbered circles; done = green check, current = blue with soft ring, pending = grey.
8. **Video block:** `st.video` (annotated clip) with an HTML timeline under it: a track, a green band for every event span, a dark playhead marker at the current event. A "Watch this moment" button sets the video `start_time` to the event start. Streamlit cannot draw on top of the video, so the event tag ("Someone is inside the restricted area" in Simple, "ZONE INTRUSION · EV-0001" in Technical) sits above the video as a coral pill.
9. **Expander:** use `st.expander`, restyled: white card, bold title, grey helper text, chevron on the right.

## 6. Pages

### 6.1 Home (`ui_product_home.png`)
Hero on `--brand`: eyebrow chip, title "Ask your CCTV footage. Get answers you can check." (the last sentence in a soft peach `#ffd5c9`), lead paragraph, two buttons ("Try the demo" goes to Investigate with the default demo clip, "See how it works" scrolls to the section), three trust ticks (Every answer cited, Checked before shown, Human review built in). On the right a tilted (-1.2deg) app window card showing a real cached answer card and a real annotated frame from the default demo clip. Hero bottom corners rounded 56 px.
Sections, in order: How it works (4 cards: See, Decide, Answer, Check, each with a line icon), What you can ask (three verdict cards: Yes, No, Can't tell, using real saved answers where they exist), Proof not promises (checklist + evidence panel using real frames), Live monitor (two lane cards), What it does not do yet (four dashed cards: falls, very short entries under 1 s, bags on the floor, modes A and C not built), closing banner with "Open the app" and "Record a clip", footer ("A CS3235 course project", "Answers are for human review, not proof.").

### 6.2 Library (`ui_pg_library.png`)
Header band, search box, filter chips (All, Evidence ready, Recorded by you), then collapsible groups from `clips_meta.json` ("Restricted zone: found", "Restricted zone: nothing found", "Left-behind bag", "Recorded and uploaded"). Each group header shows a count chip. Clip cards: thumbnail (first annotated frame or keyframe; if missing use a neutral placeholder), title, mono clip ID, chips (Evidence ready / No evidence package yet, event count or "No events", source or "Recorded by you"), buttons **Investigate** (primary) and **Report** (ghost). Local time stamps for recorded clips. Clips without evidence show a disabled Investigate with a "Process this clip" hint.

### 6.3 Investigate: Simple view (`ui_pg_investigate_simple.png`, default)
Order: header band → big question card (text area + primary Ask button; "Try also" chips below) → two columns: left verdict block, right video block → "What the camera saw" (three frames: enters, inside the area, leaves, with times) → one line "No other events were found. Falls are not checked in this version." → collapsed expander "Show technical details".
Verdict block content by decision:
- **Yes:** plain headline built by a fixed template from the event fields, NOT by the language model. Map rule names for display only: zone_intrusion → "entered the restricted area", unattended_object → "left a bag behind". Example: "Someone entered the restricted area between 00:03.7 and 00:05.4." Buttons: **Watch this moment**, then "Is this correct?" with Confirm and Flag buttons (the existing confirm/reject behaviour).
- **No:** headline "No entry found." followed by the existing app-written caveat in an amber box, and a coverage line (what range the rule covered).
- **Can't tell:** headline "Can't tell from this clip." plus the plain-language abstain reason that already exists.
- **Error (api_error):** a red-bordered card "Could not reach the language model. Try again." Never cached, never styled as an abstention.
- Always show chips: "✓ Checked · N of M" (the validator results), "For human review · not proof", and in Technical also cached/live.
- Loading: replace the verdict block with a skeleton (three grey bars pulsing) and an "Asking… 12 s" elapsed counter if the app already has one.

### 6.4 Investigate: Technical view (`ui_pg_investigate_technical.png`)
The Technical switch (stored in session state and the URL) shows everything from Simple plus: the A · B · C switch (A and C disabled with a "not implemented yet" tooltip), the track box tag text on the video label, the exact model sentence and its citations in a mono box, the full validator checklist ("How this answer was checked"), the evidence panel (rule, dwell with minimum, confidence with floor, zone, track, rule trace), the three keyframes with seek, the ±3 s event clip, and the selectable events and coverage list (confirmed_by_rule, cannot verify, did not run). Coverage panel for COV- citations stays. In Simple view the expander is closed; opening it shows the same content as Technical's lower half.

### 6.5 Report (`ui_pg_report.png`)
Amber banner "For human review · not proof…", four stat cards (Events found, Confirmed, Rejected, Not reviewed), one card per event (title in plain words + ID chip, reviewer verdict chip, three frames, facts table, rule trace, reviewer note), a "What was not checked" card (falls not implemented; rules that ran with no bag; entries under 1 s), buttons Download report and Back to Investigate. Keep the existing report/export logic.

### 6.6 Analyse (`ui_pg_analyse.png`)
Provisional banner on top. Left card: three option cards (Record from camera, Upload a clip, Live monitor; selected one has a blue border), then a numbered stepper: (1) consent tick box and source/licence field, (2) zone: shows the saved zone file name plus "Draw a zone on the current view", (3) Record: Start, **Stop live monitor**, hint "Press q or click Stop to finish. Auto-stops at 100 s." Right card: camera view or last frame, a dark mono telemetry strip (device, fps, detect fps, latency), a four-stage progress (Saved, Detecting, Building evidence, Ready) driven by the existing stage text, and an "Investigate this clip" button enabled when ready. Keep the clear error texts (for example "Clips over 2 minutes are not accepted.").

## 7. Animations (all CSS, subtle, fluid)

Rules: animate only `transform` and `opacity`; durations 150 to 450 ms; easing `cubic-bezier(.2,.8,.2,1)` for entrances and `cubic-bezier(.2,.9,.3,1.3)` for pops; every animation is disabled under `@media (prefers-reduced-motion: reduce)`. Define keyframes once in the global CSS.

| Where | Animation |
|---|---|
| Page load | Cards and sections fade up 12 px, 400 ms, staggered by 60 ms (use `animation-delay` via nth-child) |
| Cards | Hover: lift 3 px, border turns to the accent colour, 180 ms |
| Buttons | Hover lift 2 px; press (active) sinks 2 px; focus ring 3 px `--brand` |
| Verdict badge | Pops in (scale .2 → 1.12 → 1, small rotation) 600 ms, replays on every new answer (see remount trick) |
| Validator checks | Each tick pops in, staggered 80 ms |
| Answer text | Fades up 8 px after the badge, 120 ms delay |
| Loading | Skeleton bars pulse opacity .35 ↔ .9 at 1 s; spinner on the Ask button |
| Event tag on video | Fades and slides in when the event is selected |
| Timeline | Green event band gently pulses (opacity) once on load; playhead marker eases to its position (`transition: left .25s`) |
| Live monitor dot | Pulsing ring 1.4 s loop |
| Thumbnails | Hover scale 1.03 and tilt -1deg |
| Expander | Content fades down on open (180 ms) |
| Stepper | Current step has a soft ring that pulses once; done steps pop their check |
| Nav | Active pill background fades; hover shows the tint |
| Home hero | Window card floats up 8 px on a slow 6 s loop; circles drift 10 px (very slow) |

## 8. Phases

**Phase 1 (about 45 minutes):** theme files, fonts, global CSS, top bar and routing, Library, Investigate (Simple and Technical), shared components and animations. Then run all four test files, check URL restore, and take screenshots at 1440×900 and 1280×800 of Library, Investigate Simple (Yes), Investigate Technical, Investigate No, Can't tell and loading states. Report and stop.

**Phase 2 (about 45 minutes, after approval):** Home, Report, Analyse. Same checks and screenshots. Include the Live monitor popover and the Stop button state.

## 9. Acceptance checklist (include the result of each line in your report)

- [ ] No gradients anywhere; colours come from tokens only.
- [ ] Looks like the reference images at 1440 px and still correct at 1280 and 1920 px; no horizontal scrollbar.
- [ ] Simple view hides IDs, confidence, rule trace, validator list and the A/B/C switch; Technical shows them. The choice survives refresh.
- [ ] Yes, No (with caveat), Can't tell, error and loading all render correctly and match the colour roles.
- [ ] Nav does not reload the app or lose session state; refresh restores page, clip, question and view.
- [ ] Animations play on load and on each new answer, not on unrelated reruns; reduced-motion disables them.
- [ ] Fonts load offline.
- [ ] All four test files pass, same counts as before.
- [ ] No rule, threshold, prompt, validator or schema file changed (list the files you changed).
- [ ] A short list of anything that could not match the images exactly and what you did instead.
