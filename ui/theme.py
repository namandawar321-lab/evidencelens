"""Design tokens and the one global stylesheet.

Every colour in the app comes from the variables below. Do not hard-code
hex colours in other modules.
"""

GLOBAL_CSS = """
<style>
@font-face {
  font-family: "Plus Jakarta Sans";
  font-style: normal;
  font-weight: 500;
  font-display: swap;
  src: url("/app/static/fonts/plus-jakarta-sans-500.woff2") format("woff2");
}
@font-face {
  font-family: "Plus Jakarta Sans";
  font-style: normal;
  font-weight: 600;
  font-display: swap;
  src: url("/app/static/fonts/plus-jakarta-sans-600.woff2") format("woff2");
}
@font-face {
  font-family: "Plus Jakarta Sans";
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url("/app/static/fonts/plus-jakarta-sans-700.woff2") format("woff2");
}
@font-face {
  font-family: "Plus Jakarta Sans";
  font-style: normal;
  font-weight: 800;
  font-display: swap;
  src: url("/app/static/fonts/plus-jakarta-sans-800.woff2") format("woff2");
}
@font-face {
  font-family: "JetBrains Mono";
  font-style: normal;
  font-weight: 500;
  font-display: swap;
  src: url("/app/static/fonts/jetbrains-mono-500.woff2") format("woff2");
}
@font-face {
  font-family: "JetBrains Mono";
  font-style: normal;
  font-weight: 600;
  font-display: swap;
  src: url("/app/static/fonts/jetbrains-mono-600.woff2") format("woff2");
}
:root {
  --bg: #f4f6fb;
  --card: #ffffff;
  --tint: #e8eefe;
  --line: #dfe5f1;
  --ink: #0e1a3a;
  --mute: #5a6785;
  --brand: #2b5cff;
  --brand-dark: #1f45cc;
  --coral: #ff6b4a;
  --ok: #12a15a;
  --okbg: #dff5e9;
  --info: #2b5cff;
  --infobg: #e3eaff;
  --warn: #9a5b00;
  --warnbg: #ffefc9;
  --bad: #d93a3a;
  --code: #e8eefe;
  --hero-a: #3d6bff;
  --hero-b: #2450e6;
  --peach: #ffd5c9;
  --shadow: 0 10px 30px rgba(43, 92, 255, .08);
  --s1: 4px;
  --s2: 8px;
  --s3: 12px;
  --s4: 16px;
  --s5: 24px;
  --s6: 32px;
  --s7: 48px;
  --s8: 72px;
  --ease: cubic-bezier(.2, .8, .2, 1);
  --pop: cubic-bezier(.2, .9, .3, 1.3);
}
html, body, .stApp, [data-testid="stAppViewContainer"] {
  background: var(--bg) !important;
  color: var(--ink);
  font-family: "Plus Jakarta Sans", system-ui, sans-serif;
  font-size: 16px;
}
.stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp button, .stApp label,
.stApp input, .stApp textarea, .stApp li, .stApp span.el-word, .el-title, .el-sub, .el-crumb {
  font-family: "Plus Jakarta Sans", system-ui, sans-serif !important;
}
[data-testid="stIconMaterial"], .material-symbols-rounded, [class*="material-symbols"] {
  font-family: "Material Symbols Rounded" !important;
}
h1.el-title {
  font-weight: 800 !important;
  font-size: clamp(30px, 2.6vw, 42px) !important;
  letter-spacing: -0.03em !important;
}
[data-testid="stMarkdownContainer"] p,
[data-testid="stWidgetLabel"] p,
[data-testid="stCaptionContainer"] {
  color: var(--ink);
  font-family: "Plus Jakarta Sans", system-ui, sans-serif;
}
button, input, textarea, [data-baseweb="select"] {
  font-family: "Plus Jakarta Sans", system-ui, sans-serif !important;
}
header[data-testid="stHeader"], footer, #MainMenu,
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] { display: none !important; }
.block-container {
  max-width: 1440px;
  padding: 0 clamp(16px, 5vw, 72px) 60px !important;
}
.stApp, .main, [data-testid="stAppViewContainer"] { max-width: 100%; }
img, [data-testid="stImage"] img {
  max-width: 100% !important;
  object-fit: cover;
  border-radius: 16px;
}
video {
  width: 100% !important;
  max-width: 100% !important;
  max-height: 70vh !important;
  height: auto !important;
  aspect-ratio: 4 / 3;
  object-fit: contain;
  background: var(--ink);
  border-radius: 16px;
}
@media (max-width: 1100px) {
  [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    flex: 1 1 100% !important;
    width: 100% !important;
    min-width: 100% !important;
  }
}
.st-key-topbar {
  background: var(--card);
  border-bottom: 1px solid var(--line);
  min-height: 76px;
  box-sizing: border-box;
  width: calc(100% + 2 * clamp(16px, 5vw, 72px)) !important;
  max-width: none !important;
  margin-left: calc(-1 * clamp(16px, 5vw, 72px));
  margin-right: calc(-1 * clamp(16px, 5vw, 72px));
  padding: var(--s2) clamp(16px, 5vw, 72px) !important;
  position: sticky;
  top: 0;
  z-index: 30;
}
.el-logo { display: flex; align-items: center; gap: var(--s3); margin: 0; }
.el-markbox {
  width: 36px; height: 36px; border-radius: 10px;
  background: var(--brand); color: var(--card);
  display: inline-flex; align-items: center; justify-content: center;
}
.el-word { font-weight: 800; font-size: 18px; color: var(--ink); letter-spacing: -0.03em; }
[class*="st-key-nav-"] button,
[class*="st-key-navon-"] button,
[class*="st-key-view-"] button,
[class*="st-key-viewon-"] button {
  background: transparent !important;
  color: var(--ink) !important;
  border: none !important;
  border-radius: 999px !important;
  box-shadow: none !important;
  font-weight: 600 !important;
}
[class*="st-key-navon-"] button,
[class*="st-key-viewon-"] button {
  background: var(--tint) !important;
  color: var(--brand) !important;
  font-weight: 700 !important;
  animation: el-fade 180ms var(--ease) both;
}
.st-key-top-live button {
  background: var(--coral) !important;
  color: var(--card) !important;
  border: none !important;
  border-radius: 999px !important;
  font-weight: 700 !important;
}
.st-key-top-live button::before {
  content: "";
  display: inline-block;
  width: 8px; height: 8px; margin-right: 8px;
  border-radius: 50%;
  background: var(--card);
  box-shadow: 0 0 0 0 rgba(255, 255, 255, .7);
  animation: el-live 1.4s ease-out infinite;
  vertical-align: middle;
}
[data-testid="stBaseButton-primary"] button,
button[kind="primary"] {
  background: var(--brand) !important;
  color: var(--card) !important;
  border: none !important;
  border-radius: 12px !important;
}
[data-testid="stBaseButton-primary"] button:hover,
button[kind="primary"]:hover { background: var(--brand-dark) !important; }
[data-testid="stBaseButton-secondary"] button,
button[kind="secondary"] {
  border-radius: 12px !important;
  border: 1px solid var(--line) !important;
  background: var(--card) !important;
  color: var(--ink) !important;
}
[data-testid="stButton"] button {
  white-space: normal !important;
  height: auto !important;
  min-height: 2.4rem;
  transition: transform 180ms var(--ease), box-shadow 180ms var(--ease);
}
[data-testid="stButton"] button:hover { transform: translateY(-2px); }
[data-testid="stButton"] button:active { transform: translateY(2px); }
[data-testid="stButton"] button:focus-visible {
  outline: 3px solid var(--brand);
  outline-offset: 2px;
}
[data-testid="stButton"] button p {
  white-space: normal !important;
  overflow: visible !important;
  text-overflow: clip !important;
  line-height: 1.25;
}
.el-band {
  background: var(--tint);
  margin-left: calc(-1 * clamp(16px, 5vw, 72px));
  margin-right: calc(-1 * clamp(16px, 5vw, 72px));
  padding: var(--s6) clamp(16px, 5vw, 72px) var(--s5);
  animation: el-rise 400ms var(--ease) both;
}
.el-crumb {
  margin: 0 0 var(--s2) 0;
  color: var(--mute);
  font-size: 13px;
  letter-spacing: .09em;
  text-transform: uppercase;
  font-weight: 600;
}
.el-title {
  margin: 0;
  color: var(--ink);
  font-size: clamp(30px, 2.6vw, 42px);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.1;
}
.el-sub { margin: var(--s2) 0 0 0; color: var(--mute); font-size: 16px; }
.el-section {
  margin: var(--s6) 0 var(--s3) 0;
  font-size: clamp(22px, 2vw, 28px);
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--ink);
}
.el-kicker {
  margin: var(--s4) 0 var(--s2) 0;
  color: var(--mute);
  font-size: 12.5px;
  letter-spacing: .09em;
  text-transform: uppercase;
  font-weight: 700;
}
.st-key-qcard {
  background: var(--card);
  border: 1px solid var(--line) !important;
  border-radius: 24px;
  padding: var(--s4) var(--s5) var(--s3) !important;
  box-shadow: var(--shadow);
  animation: el-rise 400ms 60ms var(--ease) both;
}
.el-verdict {
  display: flex;
  gap: var(--s4);
  align-items: flex-start;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 24px;
  padding: var(--s5);
  box-shadow: var(--shadow);
}
.el-v-yes { background: var(--okbg); }
.el-v-no { background: var(--infobg); }
.el-v-abstain { background: var(--warnbg); }
.el-badge-pop {
  width: 72px; height: 72px; min-width: 72px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 32px; font-weight: 800; color: var(--card);
  animation: el-pop 450ms var(--pop) both;
}
.el-badge-yes { background: var(--ok); }
.el-badge-no { background: var(--info); }
.el-badge-abstain { background: var(--warn); }
.el-verdict-word {
  margin: 0;
  font-size: clamp(40px, 3.4vw, 56px);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1;
  color: var(--ink);
}
.el-answer-line {
  margin: var(--s2) 0 var(--s3) 0;
  font-size: 16px;
  color: var(--ink);
  animation: el-rise-sm 400ms 120ms var(--ease) both;
}
.el-chip {
  display: inline-block;
  border-radius: 999px;
  padding: 4px 10px;
  margin: 0 8px 8px 0;
  font-size: 13px;
  font-weight: 700;
  border: 1px solid var(--line);
}
.el-chip-ok { background: var(--okbg); color: var(--ok); }
.el-chip-info { background: var(--infobg); color: var(--info); }
.el-chip-warn { background: var(--warnbg); color: var(--warn); }
.el-chip-mute { background: var(--tint); color: var(--mute); }
.el-chip-bad { background: var(--card); color: var(--bad); border-color: var(--bad); }
.el-tag {
  display: inline-block;
  background: var(--coral);
  color: var(--card);
  border-radius: 999px;
  padding: 6px 12px;
  font-weight: 700;
  font-size: 13px;
  margin: 0 0 var(--s2) 0;
  animation: el-tag 180ms var(--ease) both;
}
.stApp .el-mono, .stApp .el-mono-box, .stApp .el-id, .stApp code,
.stApp .el-clip-id, .stApp .el-tick {
  font-family: "JetBrains Mono", ui-monospace, monospace !important;
}
.el-mono-box {
  background: var(--code);
  color: var(--ink);
  border-radius: 12px;
  padding: var(--s3) var(--s4);
  margin: var(--s2) 0;
  white-space: pre-wrap;
}
.el-caveat, .el-amber {
  background: var(--warnbg);
  color: var(--warn);
  font-weight: 700;
  padding: var(--s3) var(--s4);
  margin: var(--s2) 0;
  border-radius: 12px;
  border: 1px solid var(--line);
}
.el-api {
  background: var(--card);
  color: var(--bad);
  font-weight: 700;
  padding: var(--s4);
  margin: var(--s2) 0;
  border: 1px solid var(--bad);
  border-radius: 16px;
}
.el-replay {
  background: var(--tint);
  color: var(--ink);
  padding: var(--s2) var(--s3);
  margin: var(--s2) 0;
  border-radius: 12px;
}
.el-checks {
  background: var(--card);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: var(--s3) var(--s4);
  margin: var(--s2) 0;
}
.el-checks .el-label { color: var(--ink); }
.el-pass-line { color: var(--ok); font-weight: 700; }
.el-fail-line { color: var(--bad); font-weight: 700; }
.el-note-line { color: var(--mute); }
.el-tick-in { animation: el-pop 300ms var(--pop) both; }
.el-abstain-dash {
  border: 2px dashed var(--warn);
  background: var(--warnbg);
  color: var(--ink);
  padding: var(--s4);
  margin: var(--s2) 0;
  border-radius: 16px;
}
.el-card { border-radius: 16px; padding: var(--s4); margin: var(--s2) 0; color: var(--ink); }
.el-yes { background: var(--okbg); }
.el-no { background: var(--infobg); }
.el-neutral { background: var(--tint); }
.el-label { font-weight: 700; font-size: 15px; margin: 0 0 var(--s2) 0; }
.el-clip-id { color: var(--mute); font-size: 13px; margin: 0 0 var(--s2) 0; }
.el-note { color: var(--mute); margin: 0 0 var(--s2) 0; }
.el-ph {
  background: var(--tint);
  color: var(--mute);
  border-radius: 16px;
  min-height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}
.el-timeline {
  background: var(--card);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: var(--s3) var(--s4);
  margin: var(--s3) 0 var(--s4);
}
.el-tl-label { color: var(--ink); font-weight: 700; margin: 0 0 var(--s2) 0; }
.el-tl-track {
  position: relative; height: 14px;
  background: var(--tint);
  border-radius: 999px;
  border: 1px solid var(--line);
}
.el-span {
  position: absolute; top: 0; height: 14px;
  background: var(--ok);
  border-radius: 999px;
  animation: el-band 450ms var(--ease) both;
}
.el-mark { position: absolute; top: -3px; width: 2px; height: 20px; background: var(--ink); }
.el-playhead {
  position: absolute; top: -6px; width: 3px; height: 26px;
  background: var(--ink);
  transition: left .25s var(--ease);
}
.el-tl-times { position: relative; height: 1.2rem; margin-top: var(--s2); }
.el-tick {
  position: absolute; top: 0; color: var(--mute); font-size: 12px;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  white-space: nowrap;
}
.el-footer {
  color: var(--mute);
  background: var(--card);
  margin-top: var(--s7);
  border-top: 1px solid var(--line);
  padding-top: var(--s4);
  font-size: 14px;
}
.el-table { width: 100%; border-collapse: collapse; background: var(--card); color: var(--ink); }
.el-table th, .el-table td {
  border: 1px solid var(--line);
  padding: var(--s2) var(--s3);
  text-align: left;
  vertical-align: top;
}
.el-table th { background: var(--tint); color: var(--ink); }
.el-skel-wrap { padding: var(--s4) 0; }
.el-skel {
  height: 14px;
  border-radius: 8px;
  background: var(--line);
  margin: 0 0 var(--s3) 0;
  animation: el-pulse 1s ease-in-out infinite;
}
.el-asking { color: var(--mute); font-weight: 700; }
.el-popcard {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: var(--s4);
  box-shadow: var(--shadow);
  margin: var(--s2) 0 var(--s4);
}
[data-testid="stExpander"] {
  background: var(--card);
  border: 1px solid var(--line) !important;
  border-radius: 24px;
}
[data-testid="stExpanderDetails"] { animation: el-fade 180ms var(--ease) both; }
[data-testid="column"]:has(.el-card-marker) {
  transition: transform 180ms var(--ease);
}
[data-testid="column"]:has(.el-card-marker):hover {
  transform: translateY(-3px);
}
[data-testid="column"]:has(.el-card-marker):hover [data-testid="stImage"] img {
  transform: scale(1.03) rotate(-1deg);
}
[data-testid="stImage"] img { transition: transform 180ms var(--ease); }
@keyframes el-rise {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: none; }
}
@keyframes el-rise-sm {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}
@keyframes el-pop {
  0% { opacity: 0; transform: scale(.2) rotate(-8deg); }
  70% { transform: scale(1.12) rotate(2deg); }
  100% { opacity: 1; transform: scale(1) rotate(0); }
}
@keyframes el-fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes el-tag {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}
@keyframes el-band { from { opacity: .35; } to { opacity: 1; } }
@keyframes el-pulse {
  0%, 100% { opacity: .9; }
  50% { opacity: .35; }
}
@keyframes el-live {
  0% { box-shadow: 0 0 0 0 rgba(255, 255, 255, .75); }
  100% { box-shadow: 0 0 0 8px rgba(255, 255, 255, 0); }
}
[class*="st-key-nav-"] button,
[class*="st-key-view-"] button {
  background: transparent !important;
  color: var(--ink) !important;
  border: none !important;
  box-shadow: none !important;
}
[class*="st-key-navon-"] button,
[class*="st-key-viewon-"] button {
  background: var(--tint) !important;
  color: var(--brand) !important;
  border: none !important;
  font-weight: 700 !important;
}
.st-key-top-live button {
  background: var(--coral) !important;
  color: var(--card) !important;
  border: none !important;
}
.st-key-homehero, .st-key-homeclose {
  position: relative;
  overflow: hidden;
  background: var(--brand);
  color: var(--card);
  box-sizing: border-box;
  width: calc(100% + 2 * clamp(16px, 5vw, 72px)) !important;
  max-width: none !important;
  margin-left: calc(-1 * clamp(16px, 5vw, 72px));
  margin-right: calc(-1 * clamp(16px, 5vw, 72px));
  padding: var(--s7) clamp(16px, 5vw, 72px) var(--s8);
}
.st-key-homehero { border-radius: 0 0 56px 56px; }
.st-key-homeclose { border-radius: 56px 56px 0 0; margin-top: var(--s7); }
.st-key-homehero::before, .st-key-homehero::after,
.st-key-homeclose::before, .st-key-homeclose::after {
  content: "";
  position: absolute;
  border-radius: 50%;
  z-index: 0;
  pointer-events: none;
}
.st-key-homehero::before, .st-key-homeclose::before {
  width: 280px; height: 280px; background: var(--hero-a);
  top: -80px; right: 8%;
  animation: el-drift 16s ease-in-out infinite;
}
.st-key-homehero::after, .st-key-homeclose::after {
  width: 180px; height: 180px; background: var(--hero-b);
  bottom: -40px; left: 6%;
  animation: el-drift 12s ease-in-out infinite reverse;
}
.st-key-homehero [data-testid="stHorizontalBlock"],
.st-key-homeclose [data-testid="stHorizontalBlock"] { position: relative; z-index: 1; }
.el-hero-chip {
  display: inline-block;
  background: var(--hero-a);
  color: var(--card);
  border-radius: 999px;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 700;
  margin: 0 0 var(--s4) 0;
}
.el-hero-title {
  margin: 0;
  color: var(--card);
  font-weight: 800;
  font-size: clamp(44px, 4.2vw, 68px);
  letter-spacing: -0.035em;
  line-height: 1.05;
}
.el-hero-title .el-hero-peach { color: var(--peach); }
.el-hero-lead { color: var(--card); font-size: 16px; max-width: 40rem; }
.st-key-homehero [data-testid="stMarkdownContainer"] p,
.st-key-homehero [data-testid="stMarkdownContainer"] li,
.st-key-homehero [data-testid="stMarkdownContainer"] h1,
.st-key-homeclose [data-testid="stMarkdownContainer"] h2 {
  color: var(--card);
}
.st-key-homehero .el-hero-window p,
.st-key-homehero .el-hero-window .el-verdict-word { color: var(--ink); }
.st-key-homehero .el-hero-window .el-kicker,
.st-key-homehero .el-hero-window .el-clip-id { color: var(--mute); }
[data-testid="stMarkdownContainer"] .el-home-sub,
[data-testid="stMarkdownContainer"] .el-home-card p,
[data-testid="stMarkdownContainer"] .el-dash p,
[data-testid="stMarkdownContainer"] .el-kicker { color: var(--mute); }
[data-testid="stMarkdownContainer"] .el-trace { color: var(--ink); }
.el-home-card img { width: 100%; border-radius: 16px; aspect-ratio: 4 / 3; object-fit: cover; }
.st-key-homehero [data-testid="stHorizontalBlock"] [data-testid="stHorizontalBlock"] { align-items: center; }
.st-key-homehero [data-testid="stElementContainer"]:has(iframe) {
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  overflow: hidden;
}
.el-hero-ticks { list-style: none; padding: 0; margin: var(--s4) 0 0 0; }
.el-hero-ticks li { color: var(--card); font-weight: 700; margin: 0 0 var(--s2) 0; }
a.el-hero-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 2.4rem;
  padding: 0 var(--s4);
  border-radius: 12px;
  border: 1px solid var(--card);
  color: var(--card);
  font-weight: 700;
  text-decoration: none;
}
.st-key-home-try button {
  background: var(--coral) !important;
  color: var(--card) !important;
  border: none !important;
  border-radius: 12px !important;
}
.el-hero-window {
  background: var(--card);
  color: var(--ink);
  border-radius: 24px;
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
  padding: var(--s4);
  transform: rotate(-1.2deg);
  animation: el-float 6s ease-in-out infinite;
}
.el-win-bar { display: flex; gap: 6px; align-items: center; margin: 0 0 var(--s3) 0; color: var(--mute); font-size: 13px; font-weight: 700; }
.el-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.el-dot-ok { background: var(--ok); }
.el-dot-warn { background: var(--warn); }
.el-dot-bad { background: var(--bad); }
.el-hero-window img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 16px; }
.el-home-sec { animation: el-rise 400ms var(--ease) both; margin-top: var(--s7); }
.el-home-h2 {
  margin: 0 0 var(--s2) 0;
  color: var(--ink);
  font-size: clamp(30px, 2.6vw, 42px);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.1;
}
.el-home-sub { color: var(--mute); margin: 0 0 var(--s5) 0; }
.st-key-home-record button, .st-key-home-open button {
  border-radius: 12px !important;
}
.st-key-home-open button {
  background: var(--coral) !important;
  color: var(--card) !important;
  border: none !important;
}
.st-key-home-record button {
  background: transparent !important;
  color: var(--card) !important;
  border: 1px solid var(--card) !important;
}
.el-home-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--s5);
}
.el-home-card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 24px;
  padding: var(--s5);
  box-shadow: var(--shadow);
}
.el-home-card h3 { margin: var(--s3) 0 var(--s2) 0; font-weight: 800; letter-spacing: -0.03em; }
.el-home-card p, .el-dash p { margin: 0; color: var(--mute); }
.el-icon { width: 36px; height: 36px; color: var(--brand); }
.el-verdict-mini { border-radius: 24px; padding: var(--s5); border: 1px solid var(--line); }
.el-vmini-yes { background: var(--okbg); }
.el-vmini-no { background: var(--infobg); }
.el-vmini-abstain { background: var(--warnbg); }
.el-dash {
  background: var(--card);
  border: 1px dashed var(--line);
  border-radius: 24px;
  padding: var(--s5);
}
.el-trace {
  font-family: "JetBrains Mono", ui-monospace, monospace;
  background: var(--code);
  color: var(--ink);
  border-radius: 12px;
  padding: var(--s3) var(--s4);
  white-space: pre-wrap;
}
.el-home-foot { color: var(--mute); margin-top: var(--s6); }
.st-key-reportband {
  background: var(--tint);
  box-sizing: border-box;
  width: calc(100% + 2 * clamp(16px, 5vw, 72px)) !important;
  max-width: none !important;
  margin-left: calc(-1 * clamp(16px, 5vw, 72px));
  margin-right: calc(-1 * clamp(16px, 5vw, 72px));
  padding: var(--s6) clamp(16px, 5vw, 72px) var(--s5) !important;
  animation: el-rise 400ms var(--ease) both;
}
.el-report-sec { margin-top: var(--s6); animation: el-rise 400ms var(--ease) both; }
.el-report-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--s4);
}
.el-stat, [class*="st-key-rpt-"] {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 24px;
  padding: var(--s5);
  box-shadow: var(--shadow);
  animation: el-rise 400ms var(--ease) both;
  transition: transform 180ms var(--ease), border-color 180ms var(--ease);
}
.el-stat:hover, [class*="st-key-rpt-"]:hover {
  transform: translateY(-3px);
  border-color: var(--brand);
}
[class*="st-key-rpt-"] { margin-top: var(--s5); }
[class*="st-key-rpt-0-"] { animation-delay: 60ms; }
[class*="st-key-rpt-1-"] { animation-delay: 120ms; }
[class*="st-key-rpt-2-"] { animation-delay: 180ms; }
[class*="st-key-rpt-3-"] { animation-delay: 240ms; }
[data-testid="stMarkdownContainer"] .el-stat-n {
  margin: 0;
  color: var(--ink);
  font-size: clamp(32px, 3vw, 44px);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1;
}
[data-testid="stMarkdownContainer"] .el-stat .el-kicker,
[data-testid="stMarkdownContainer"] .el-report-note,
[class*="st-key-rpt-"] [data-testid="stMarkdownContainer"] .el-kicker,
.el-report-sec .el-kicker { color: var(--mute); }
[class*="st-key-rpt-"] [data-testid="stImage"] img {
  width: 100% !important;
  height: 240px !important;
  object-fit: cover !important;
}
.el-miss {
  height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--s3);
  border: 1px dashed var(--line);
  border-radius: 16px;
  background: var(--tint);
  color: var(--mute);
  font-weight: 700;
}
.el-report-h {
  margin: 0 0 var(--s3) 0;
  color: var(--ink);
  font-size: clamp(22px, 2vw, 28px);
  font-weight: 800;
  letter-spacing: -0.03em;
}
@keyframes el-float {
  0%, 100% { transform: rotate(-1.2deg) translateY(0); }
  50% { transform: rotate(-1.2deg) translateY(-8px); }
}
@keyframes el-drift {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(10px, -8px); }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
  }
}
</style>
"""
