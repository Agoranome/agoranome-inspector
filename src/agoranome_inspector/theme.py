"""The look of the pages people read on the site (index.html, best-buy/): agoranome.com's own theme.

Shariar asked on 11 Nov 2026 for the open sheet to match the rest of agoranome.com, and the sheet is served at
inspector.agoranome.com. The pages keep every figure and sentence they had; only the frame is the website's: its
dark navy and baby blue, its system fonts, its header with the mark and its footer. Everything is a static file written
beside the pages (style.css, mark.svg), so nothing is fetched from another origin and the site works offline from a
copy of the gh-pages branch. The tokens are copied from agoranome.com's site.css; keep them in step by hand.
"""

from __future__ import annotations

import html
from pathlib import Path

HOME = "https://agoranome.com/"
INSPECTOR_PAGE = "https://agoranome.com/inspector"
STYLE = "style.css"
MARK = "mark.svg"

# Agoranome's mark, as agoranome.com serves it at /site/mark.svg.
MARK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Agoranome">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#a9ddf5"/>
      <stop offset="0.55" stop-color="#89cff0"/>
      <stop offset="1" stop-color="#c4b5fd"/>
    </linearGradient>
  </defs>
  <rect x="2" y="2" width="60" height="60" rx="16" fill="#0f1a26"/>
  <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="15.25" fill="none" stroke="#89cff0" stroke-opacity=".28"
        stroke-width="1.5"/>
  <g fill="none" stroke="url(#g)" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M14 25 32 14l18 11Z"/>
    <path d="M19 30v15M28 30v15M36 30v15M45 30v15"/>
    <path d="M14 50h36"/>
  </g>
</svg>
"""

CSS = """/* agoranome.com's theme for the inspector's pages (src/agoranome_inspector/theme.py). Licensed Apache-2.0. */
:root {
  color-scheme: dark;
  --page: #0a121b;
  --surface: rgba(17, 30, 44, 0.72);
  --surface-solid: #0f1a26;
  --surface-2: #132232;
  --ink: #eef7fd;
  --ink-2: #b4d3e6;
  --muted: #86a1b6;
  --border: rgba(137, 207, 240, 0.14);
  --border-strong: rgba(137, 207, 240, 0.32);
  --wash: rgba(137, 207, 240, 0.07);
  --baby: #89cff0;
  --baby-strong: #a9ddf5;
  --lilac: #c4b5fd;
  --mint: #a7f0d2;
  --radius: 18px;
  --radius-sm: 12px;
  --shadow: 0 1px 0 rgba(255, 255, 255, 0.04) inset, 0 20px 50px -24px rgba(0, 0, 0, 0.7);
  --sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
}

*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--page);
  color: var(--ink);
  font: 16px/1.6 var(--sans);
  -webkit-font-smoothing: antialiased;
  overflow-x: hidden;
}
/* A faint dot grid that fades out down the page, and three soft glows behind the top, as on agoranome.com. */
body::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: -2;
  background-image: radial-gradient(rgba(137, 207, 240, 0.09) 1px, transparent 1px);
  background-size: 28px 28px;
  -webkit-mask-image: linear-gradient(to bottom, #000 0%, transparent 70%);
  mask-image: linear-gradient(to bottom, #000 0%, transparent 70%);
}
.glow { position: absolute; inset: 0 0 auto 0; height: 900px; z-index: -1; overflow: hidden; pointer-events: none; }
.orb { position: absolute; border-radius: 50%; filter: blur(80px); opacity: 0.5; }
.orb-1 { width: 520px; height: 520px; left: -140px; top: -180px; background: rgba(137, 207, 240, 0.40); }
.orb-2 { width: 460px; height: 460px; right: -120px; top: -60px; background: rgba(196, 181, 253, 0.30); }
.orb-3 { width: 380px; height: 380px; left: 38%; top: 260px; background: rgba(167, 240, 210, 0.16); }

a { color: var(--baby); text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { color: var(--baby-strong); }
:focus-visible { outline: 2px solid var(--baby); outline-offset: 3px; border-radius: 6px; }
code, pre { font-family: var(--mono); font-size: 0.88em; }
p code, li code { background: var(--wash); border: 1px solid var(--border); border-radius: 6px; padding: 0.08em 0.4em;
  color: var(--baby-strong); overflow-wrap: anywhere; }

.wrap { width: min(1160px, 100% - 32px); margin-inline: auto; }
.skip { position: absolute; left: -999px; top: 8px; background: var(--baby); color: var(--page); padding: 8px 14px;
  border-radius: 8px; z-index: 10; }
.skip:focus { left: 16px; }

.site-header { position: sticky; top: 0; z-index: 5; backdrop-filter: saturate(160%) blur(14px);
  -webkit-backdrop-filter: saturate(160%) blur(14px); background: rgba(10, 18, 27, 0.66);
  border-bottom: 1px solid var(--border); }
.nav { display: flex; align-items: center; gap: 28px; height: 64px; }
.brand { display: inline-flex; align-items: center; gap: 10px; color: var(--ink); text-decoration: none;
  font-weight: 650; letter-spacing: -0.01em; font-size: 1.06rem; }
.brand:hover { color: var(--ink); }
.tm { font-size: 0.55em; line-height: 0; vertical-align: super; margin-left: 1px; font-weight: 500; }
.nav-links { display: flex; gap: 4px; list-style: none; margin: 0; padding: 0; flex: 1; }
.nav-links a { display: block; padding: 6px 12px; border-radius: 999px; color: var(--ink-2); text-decoration: none;
  font-size: 0.94rem; transition: background 0.2s, color 0.2s; }
.nav-links a:hover { color: var(--ink); background: var(--wash); }
.nav-links a[aria-current="page"] { color: var(--ink); background: rgba(137, 207, 240, 0.12); }

.doc { width: min(920px, 100% - 32px); margin-inline: auto; padding: 72px 0 64px; }
.doc-wide { width: min(1160px, 100% - 32px); }
.eyebrow { text-transform: uppercase; letter-spacing: 0.14em; font-size: 0.76rem; font-weight: 650; color: var(--baby);
  margin: 0 0 12px; }
h1 { font-size: clamp(2.2rem, 5vw, 3.6rem); line-height: 1.04; letter-spacing: -0.035em; margin: 0 0 22px;
  font-weight: 720; }
h2 { font-size: clamp(1.4rem, 2.6vw, 1.9rem); line-height: 1.15; letter-spacing: -0.025em; margin: 56px 0 14px;
  font-weight: 690; }
h1 + h2, .lead + h2 { margin-top: 40px; }
p, li { color: var(--ink-2); }
p { margin: 0 0 14px; }
.lead { font-size: clamp(1.06rem, 1.6vw, 1.2rem); max-width: 40em; margin-bottom: 8px; }
ul { margin: 0 0 16px; padding-left: 1.25em; }
li { margin: 2px 0; }
li::marker { color: var(--baby); }

table { display: block; width: 100%; max-width: 100%; overflow-x: auto; border-collapse: separate; border-spacing: 0;
  margin: 8px 0 18px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm);
  box-shadow: var(--shadow); font-size: 0.92rem; }
th, td { text-align: left; vertical-align: top; padding: 10px 14px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); background: var(--surface-2); font-size: 0.74rem; font-weight: 650; text-transform: uppercase;
  letter-spacing: 0.08em; white-space: nowrap; }
td { color: var(--ink-2); white-space: nowrap; }
/* Short values stay on one line; a cell holding a hash or an endpoint wraps instead. */
td:has(code) { white-space: normal; min-width: 16em; }
tr:last-child td { border-bottom: 0; }
td code { color: var(--baby-strong); font-size: 0.82rem; overflow-wrap: anywhere; word-break: break-all; }
pre { background: var(--surface-solid); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 16px 18px; overflow-x: auto; color: var(--baby-strong); line-height: 1.55; margin: 8px 0 16px; }

.site-footer { border-top: 1px solid var(--border); background: rgba(8, 14, 21, 0.7); margin-top: 24px; }
.footer-grid { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 24px 48px; padding: 40px 0 28px; }
.footer-brand p { color: var(--muted); max-width: 30em; font-size: 0.93rem; margin: 12px 0 0; }
.footer-links { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.footer-links li { margin: 0; }
.footer-links a { color: var(--muted); text-decoration: none; font-size: 0.93rem; }
.footer-links a:hover { color: var(--baby-strong); }
.footer-base { border-top: 1px solid var(--border); padding: 18px 0 28px; }
.footer-base p { margin: 0; color: var(--muted); font-size: 0.82rem; }

/* Charts (charts.py). Series colors are the data-viz method's dark categorical slots, checked on --surface-solid;
   s0 is the grey of a context bar. Text keeps the ink colors; a mark's color only says which series it is. */
.chart { margin: 18px 0 26px; padding: 20px 22px; background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); box-shadow: var(--shadow); font-variant-numeric: tabular-nums; }
.chart figcaption { margin-bottom: 14px; }
.chart-title { display: block; color: var(--ink); font-weight: 650; font-size: 1.04rem; letter-spacing: -0.01em; }
.chart-sub { display: block; color: var(--ink-2); font-size: 0.93rem; margin-top: 4px; }
.chart-note { color: var(--muted); font-size: 0.84rem; margin: 12px 0 0; }
.s0 { --c: #5f7488; } .s1 { --c: #3987e5; } .s2 { --c: #d95926; } .s3 { --c: #199e70; } .s4 { --c: #c98500; }
.s5 { --c: #d55181; }
.chart [data-v] { cursor: default; }
.chart [data-v]:hover { filter: brightness(1.18); }
.seg-row { display: grid; grid-template-columns: 8.5em 1fr; gap: 14px; align-items: center; margin: 10px 0; }
.seg-name { color: var(--ink); font-weight: 600; line-height: 1.25; }
.seg-name span { display: block; color: var(--muted); font-weight: 400; font-size: 0.8rem; }
.seg { display: flex; gap: 2px; height: 28px; }
.seg-part { flex: 0 1 0; min-width: 3px; display: flex; align-items: center; justify-content: center;
  background: var(--c); overflow: hidden; }
.seg-part:first-child { border-radius: 4px 0 0 4px; }
.seg-part:last-child { border-radius: 0 4px 4px 0; }
.seg-part:only-child { border-radius: 4px; }
.seg-part b { color: #fff; font-size: 0.8rem; font-weight: 650; }
.chart-legend { list-style: none; display: flex; flex-wrap: wrap; gap: 6px 18px; padding: 0; margin: 14px 0 0; }
.chart-legend li { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 0.86rem; }
.chart-legend li::marker { content: ""; }
.chart-legend i { width: 12px; height: 12px; border-radius: 3px; background: var(--c); flex: none; }
.bars { display: grid; gap: 6px; }
.bar-row { display: grid; grid-template-columns: minmax(10em, 14.5em) 1fr; gap: 12px; align-items: center; }
.bar-name { color: var(--ink-2); font-size: 0.88rem; line-height: 1.25; }
.bar-all .bar-name, .bar-all .bar-val { color: var(--ink); font-weight: 600; }
.bar-track { display: flex; align-items: center; gap: 8px; min-width: 0; }
.bar { height: 18px; min-width: 2px; border-radius: 0 4px 4px 0; background: var(--c); flex: none; }
.bar-val { color: var(--ink-2); font-size: 0.84rem; white-space: nowrap; }
.cols { display: flex; gap: 10px; }
.col-group { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; }
.col-bars { height: 190px; display: flex; justify-content: center; gap: 2px;
  border-bottom: 1px solid var(--border-strong); }
.col { flex: 0 1 44px; display: flex; flex-direction: column; justify-content: flex-end; align-items: center;
  min-width: 0; }
.col-val { color: var(--ink-2); font-size: 0.78rem; margin-bottom: 4px; white-space: nowrap; }
.col-bar { width: 100%; border-radius: 4px 4px 0 0; background: var(--c); }
.col-name { margin-top: 8px; text-align: center; color: var(--muted); font-size: 0.8rem; line-height: 1.3; }
.chart-scroll { overflow-x: auto; }
.chart-svg { display: block; width: 100%; min-width: 480px; height: auto; font-family: var(--sans); }
.chart-svg .grid { stroke: var(--border); stroke-width: 1; }
.chart-svg .tick { fill: var(--muted); font-size: 11px; }
.chart-svg .end { fill: var(--ink-2); font-size: 12px; }
.chart-svg .line { fill: none; stroke: var(--c); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.chart-svg .dot { fill: var(--c); stroke: var(--surface-solid); stroke-width: 2; }
.chart-table { margin-top: 12px; }
.chart-table summary { color: var(--baby); cursor: pointer; font-size: 0.86rem; width: max-content; }
.chart-table table { margin-bottom: 0; }
.chart-tip { position: fixed; z-index: 20; pointer-events: none; max-width: 280px; padding: 8px 11px;
  background: #0b1520; border: 1px solid var(--border-strong); border-radius: 10px; box-shadow: var(--shadow);
  font-size: 0.84rem; line-height: 1.4; }
.chart-tip[hidden] { display: none; }
.chart-tip strong { display: block; color: var(--ink); font-variant-numeric: tabular-nums; }
.chart-tip span { color: var(--ink-2); }

@media (max-width: 640px) {
  .nav { gap: 12px; }
  .nav-links { gap: 0; }
  .nav-links a { padding: 6px 9px; white-space: nowrap; font-size: 0.9rem; }
  .brand span { display: none; }
  .doc { padding-top: 48px; }
  .chart { padding: 16px 14px; }
  .seg-row, .bar-row { grid-template-columns: 1fr; gap: 4px; }
  .bars { gap: 10px; }
  .cols { gap: 4px; }
  .col-name { font-size: 0.72rem; }
}
"""


def page(title: str, body: str, *, depth: int = 0, wide: bool = False, current: str = "sheet",
         best_buys: bool = True) -> str:
    """A whole HTML page in the site's frame. `body` is trusted HTML the caller built and escaped; `depth` is how
    many folders below the site's root the page sits, so its links to style.css, the mark and the sheet still work.
    `best_buys` puts the best-buy sheets in the menu; leave it off until the site has them."""
    e = html.escape
    up = "../" * depth
    here = ' aria-current="page"'
    sheet_current = here if current == "sheet" else ""
    best_current = here if current == "best-buy" else ""
    best = f'      <li><a href="{up}best-buy/index.html"{best_current}>Best buys</a></li>\n' if best_buys else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#0a121b">
<link rel="icon" href="{up}{MARK}" type="image/svg+xml">
<link rel="stylesheet" href="{up}{STYLE}">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<div class="glow" aria-hidden="true"><span class="orb orb-1"></span><span class="orb orb-2"></span>
<span class="orb orb-3"></span></div>
<header class="site-header">
  <nav class="nav wrap" aria-label="Main">
    <a class="brand" href="{HOME}" aria-label="Agoranome home">
      <img src="{up}{MARK}" alt="" width="30" height="30">
      <span>Agoranome<sup class="tm">&trade;</sup></span>
    </a>
    <ul class="nav-links">
      <li><a href="{HOME}">Home</a></li>
      <li><a href="{INSPECTOR_PAGE}">Inspector</a></li>
      <li><a href="{up}index.html"{sheet_current}>Open sheet</a></li>
{best}    </ul>
  </nav>
</header>
<main id="main" class="doc{' doc-wide' if wide else ''}">
{body}
</main>
<footer class="site-footer">
  <div class="wrap footer-grid">
    <div class="footer-brand">
      <a class="brand" href="{HOME}"><img src="{up}{MARK}" alt="" width="26" height="26">
        <span>Agoranome<sup class="tm">&trade;</sup></span></a>
      <p>Fair markets for machines. The inspector asks paid endpoints for their offers, judges them by a published rule
      and signs what it sees into an open book.</p>
    </div>
    <ul class="footer-links">
      <li><a href="{HOME}">agoranome.com</a></li>
      <li><a href="{INSPECTOR_PAGE}">The inspector's key</a></li>
      <li><a href="{up}book.jsonl">The open book</a></li>
    </ul>
  </div>
  <div class="wrap footer-base">
    <p>&copy; 2026 Agoranome<sup class="tm">&trade;</sup>. The sheets are free under CC BY 4.0.</p>
  </div>
</footer>
</body>
</html>
"""


def write_assets(site: Path) -> None:
    """style.css and mark.svg at the site's root, beside index.html (rewritten each time, so they follow the code)."""
    (site / STYLE).write_text(CSS, encoding="utf-8")
    (site / MARK).write_text(MARK_SVG, encoding="utf-8")
