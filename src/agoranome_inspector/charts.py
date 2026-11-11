"""Charts on the open sheet (Shariar, 11 Nov 2026: "inspector sheet, should include insightful visualizations").

Each chart is drawn from the newest sheet of each market: from the counts its book entry signs, or from its rows, read
from the site only after their hash matches the book (publish.load_sheet). Each says in one sentence what it shows,
and each keeps its figures in a table beside it, so nothing is read from color or hover alone.

  answers     what each market's endpoints answered: one bar per market, from the book entry's counts
  trend       the share of judged offers that don't match their listing, sheet by sheet, once a market has two
  categories  that share by kind of job, for kinds with at least MIN_GROUP judged offers
  markup      when an offer asks more than its listing, how many times more (like-for-like options only)
  prices      what one call costs: each market's payable offers by price band, as shares

A market's chart needs at least MIN_GROUP offers behind it (the home page's rule for a finding), so no picture is drawn
from a handful. Bars are plain HTML sized in percent, so they fit a phone; only the trend's lines are SVG. Nothing is
fetched from another origin: the style is in style.css and the hover script is inline.

Colors are the data-viz method's dark categorical slots, checked on the page's surface (#0f1a26) with its validator
(lightness band, chroma floor, colour-blind separation, contrast: all pass), always in this order: blue, orange,
aqua, yellow, magenta. A series keeps its slot (x402 is slot 1, MPP slot 2). Text is never colored by its series.
"""

import html
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agoranome_inspector import pick as pick_lib
from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.bestbuy import LABELS

MIN_GROUP = 100
SLOTS = 5
MARKET_SLOT = {"x402": 1, "mpp": 2}
MARKET_NAMES = {"x402": "x402", "mpp": "MPP"}

# What an endpoint answered, folded into five parts in a fixed order (an unknown answer counts as the last).
PARTS: List[Tuple[str, str, Tuple[str, ...]]] = [
    ("payable", "Gave an offer an agent can pay", ("payable",)),
    ("wants_input", "Wanted a valid request before quoting", ("wants_input",)),
    ("not_asked", "Not asked or not reached", ("not_asked", "declined")),
    ("gone", "Gone or refused", ("gone", "http_4xx")),
    ("failed", "Failed, or gave no usable offer", ("http_5xx", "unreachable", "unreadable_offer", "no_payment_asked",
                                                   "other")),
]
# A share is printed inside its block only from this share up, so it fits on a phone.
INSIDE_LABEL = 0.1
# The tallest column fills this share of its box, leaving room for its value above it.
COLUMN_TOP = 84

MARKUP_BANDS: List[Tuple[Decimal, str]] = [
    (Decimal("1.1"), "less than 1.1×"), (Decimal("1.5"), "1.1 to 1.5×"), (Decimal("2"), "1.5 to 2×"),
    (Decimal("10"), "2 to 10×"), (Decimal("Infinity"), "10× or more"),
]
PRICE_BANDS: List[Tuple[Decimal, str]] = [
    (Decimal("0.001"), "under $0.001"), (Decimal("0.01"), "$0.001 to $0.01"), (Decimal("0.1"), "$0.01 to $0.10"),
    (Decimal("1"), "$0.10 to $1"), (Decimal("Infinity"), "$1 or more"),
]

e = html.escape


# --- Figures ----------------------------------------------------------------------------------------------------

def _pct(n: int, whole: int, places: int = 1) -> str:
    """n as a share of whole, never rounded to 0% or 100% unless it is."""
    if not whole:
        return "0%"
    value, step = 100 * n / whole, 10 ** -places
    if 0 < value < step / 2:
        return f"under {step:g}%"
    if n < whole and value >= 100 - step / 2:
        return f"over {100 - step:g}%"
    return f"{value:.0f}%" if places == 0 or value == int(value) else f"{value:.{places}f}%"


def _short(share: str) -> str:
    """A share as a column's cap shows it, where a phone leaves little room: "<1%" for "under 1%"."""
    return share.replace("under ", "<").replace("over ", ">")


def answer_parts(summary: Dict[str, Any]) -> List[Tuple[str, str, int]]:
    """(key, label, count) for each of the five parts, in order, from a sheet entry's answer counts."""
    counts = summary.get("answer") or {}
    known = {a for _, _, answers in PARTS for a in answers}
    out = []
    for key, label, answers in PARTS:
        n = sum(int(counts.get(a) or 0) for a in answers)
        if key == "failed":
            n += sum(int(v or 0) for a, v in counts.items() if a not in known)
        out.append((key, label, n))
    return out


def mismatch(summary: Dict[str, Any]) -> Tuple[int, int]:
    """(offers that don't match their listing, offers judged) from a sheet entry's counts."""
    m = summary.get("matches_listing") or {}
    bad = int(m.get("false") or 0)
    return bad, bad + int(m.get("true") or 0)


def by_category(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each kind of job's judged offers and how many don't match their listing, most mismatched first."""
    judged: Counter = Counter()
    bad: Counter = Counter()
    for r in rows:
        matches = (r.get("verdict") or {}).get("matches_listing")
        if matches is None:
            continue
        key = r.get("category") or "other"
        judged[key] += 1
        bad[key] += matches is False
    out = [{"category": k, "label": LABELS.get(k, k.replace("_", " ").capitalize()), "judged": n, "bad": bad[k]}
           for k, n in judged.items()]
    return sorted(out, key=lambda c: (-c["bad"] / c["judged"], c["label"]))


def markups(rows: Sequence[Dict[str, Any]]) -> List[Decimal]:
    """For each offer that asked more than its listing, how many times its listed price it asked: the largest ratio
    among the compared options (same network and asset, or method and currency), so like is set beside like."""
    out = []
    for r in rows:
        verdict = r.get("verdict") or {}
        if verdict.get("price") != "above_listed":
            continue
        ratios = []
        for d in verdict.get("differs") or []:
            try:
                asked, listed = Decimal(str(d.get("asked_amount"))), Decimal(str(d.get("listed_amount")))
            except (ArithmeticError, ValueError):
                continue
            if d.get("price") == "above_listed" and listed > 0 and asked.is_finite():
                ratios.append(asked / listed)
        if ratios:
            out.append(max(ratios))
    return out


def prices(market: str, rows: Sequence[Dict[str, Any]]) -> List[Decimal]:
    """The dollar price each payable offer asks (the pick rule's: the cheapest option it names, in USDC or a dollar
    currency), for the offers that name one."""
    out = []
    for r in rows:
        if (r.get("verdict") or {}).get("answer") != "payable":
            continue
        found = pick_lib.price(market, r)
        if found is not None:
            out.append(found[0])
    return out


def bands(values: Sequence[Decimal], edges: Sequence[Tuple[Decimal, str]]) -> List[Tuple[str, int]]:
    """How many values fall in each band; a band holds values from the edge before it up to, not including, its own."""
    counts = [0] * len(edges)
    for v in values:
        counts[next(i for i, (top, _) in enumerate(edges) if v < top)] += 1
    return [(label, counts[i]) for i, (_, label) in enumerate(edges)]


def median(values: Sequence[Decimal]) -> Optional[Decimal]:
    s = sorted(values)
    if not s:
        return None
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _times(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1')).normalize():f}×" if value < 10 else f"{value:,.0f}×"


def _usd(value: Decimal) -> str:
    return f"${value.normalize():f}" if value < 1 else f"${value:,.2f}"


# --- Pieces -----------------------------------------------------------------------------------------------------

def _mark(tag: str, cls: str, style: str, value: str, label: str, inner: str = "", attrs: str = "") -> str:
    """A mark that names its figure on hover and keyboard focus (data-v leads, data-l follows), and to a screen
    reader by its label. `style` and `attrs` are built here from numbers, never from a row."""
    return (f'<{tag} class="{cls}"' + (f' style="{style}"' if style else "") + (f" {attrs}" if attrs else "")
            + f' tabindex="0" role="img" aria-label="{e(label)}: {e(value)}" data-v="{e(value)}" '
            f'data-l="{e(label)}">{inner}</{tag}>')


def _figure(title: str, sentence: str, chart: str, legend: str, head: Sequence[str],
            rows: Sequence[Sequence[str]], note: str = "") -> str:
    table = ("<tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>"
             + "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows))
    return (f'<figure class="chart"><figcaption><span class="chart-title">{e(title)}</span>'
            f'<span class="chart-sub">{e(sentence)}</span></figcaption>{chart}{legend}'
            + (f'<p class="chart-note">{e(note)}</p>' if note else "")
            + f'<details class="chart-table"><summary>The figures</summary><table>{table}</table></details></figure>\n')


def _legend(items: Sequence[Tuple[int, str]]) -> str:
    return ('<ul class="chart-legend">' + "".join(f'<li><i class="s{slot}"></i>{e(name)}</li>' for slot, name in items)
            + "</ul>")


# --- Charts -----------------------------------------------------------------------------------------------------

def answers_chart(newest: Dict[str, Dict[str, Any]]) -> str:
    """One tall segmented bar per market: what its endpoints answered."""
    bars, table, said = [], [], []
    for market, body in newest.items():
        parts = answer_parts(body["summary"])
        whole = sum(n for _, _, n in parts)
        if whole < MIN_GROUP:
            continue
        name = MARKET_NAMES.get(market, market)
        blocks = []
        for slot, (_, label, n) in enumerate(parts, start=1):
            if not n:
                continue
            share = n / whole
            text = _pct(n, whole, 0) if share >= INSIDE_LABEL else ""
            blocks.append(_mark("span", f"seg-part s{slot}", f"flex-grow:{n}", f"{n:,} · {_pct(n, whole)}",
                                f"{name}: {label.lower()}", f"<b>{text}</b>" if text else ""))
            table.append([name, label, f"{n:,}", _pct(n, whole)])
        bars.append(f'<div class="seg-row"><div class="seg-name">{e(name)}<span>{whole:,} endpoints</span></div>'
                    f'<div class="seg">{"".join(blocks)}</div></div>')
        said.append(f"{name}: {_pct(parts[0][2], whole, 0)}"
                    + ("" if said else " gave an offer an agent can pay"))
    if not bars:
        return ""
    legend = _legend([(slot, label) for slot, (_, label, _) in enumerate(PARTS, start=1)
                      if any(r[1] == label for r in table)])
    return _figure("What the endpoints answered", "; ".join(said) + ".", "".join(bars), legend,
                   ["Market", "Answer", "Endpoints", "Share"], table)


def trend_chart(sheets: Sequence[Dict[str, Any]]) -> str:
    """Lines: each market's share of judged offers that don't match their listing, sheet by sheet. Drawn once a
    market has two sheets."""
    series: Dict[str, List[Tuple[str, int, int]]] = {}
    for x in sheets:
        body = x["body"]
        bad, judged = mismatch(body.get("summary") or {})
        if judged >= MIN_GROUP:
            series.setdefault(sheet_lib.market_of(body), []).append((_day(body), bad, judged))
    if not any(len(points) >= 2 for points in series.values()):
        return ""
    days = sorted({d for points in series.values() for d, _, _ in points})
    top = max(bad / judged for points in series.values() for _, bad, judged in points)
    ceiling = next(c for c in (0.05, 0.1, 0.2, 0.3, 0.5, 1.0) if top <= c)
    width, height, left, right, upper, lower = 640, 220, 44, 96, 14, 30
    plot_w, plot_h = width - left - right, height - upper - lower

    def x(day: str) -> float:
        return left + (plot_w * days.index(day) / (len(days) - 1) if len(days) > 1 else plot_w / 2)

    def y(share: float) -> float:
        return upper + plot_h * (1 - share / ceiling)

    grid = "".join(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="tick" x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{t * 100:.0f}%</text>'
                   for t in (0, ceiling / 2, ceiling))
    ticks = "".join(f'<text class="tick" x="{x(d):.1f}" y="{height - 8}" text-anchor="middle">{e(d[5:])}</text>'
                    for d in days)
    lines, table, legend, said = [], [], [], []
    for market, points in series.items():
        slot = MARKET_SLOT.get(market, 3)
        name = MARKET_NAMES.get(market, market)
        path = " ".join(f"{'M' if i == 0 else 'L'}{x(d):.1f},{y(b / j):.1f}" for i, (d, b, j) in enumerate(points))
        dots = "".join(_mark("circle", f"dot s{slot}", "", f"{_pct(b, j)} · {b:,} of {j:,}",
                             f"{name}, sheet of {d}", attrs=f'cx="{x(d):.1f}" cy="{y(b / j):.1f}" r="5"')
                       for d, b, j in points)
        d_last, b_last, j_last = points[-1]
        lines.append(f'<path class="line s{slot}" d="{path}"/>{dots}'
                     f'<text class="end" x="{x(d_last) + 10:.1f}" y="{y(b_last / j_last) + 4:.1f}">'
                     f'{e(name)} {_pct(b_last, j_last)}</text>')
        table += [[name, d, f"{b:,}", f"{j:,}", _pct(b, j)] for d, b, j in points]
        legend.append((slot, name))
        if len(points) >= 2:
            first = points[0][1] / points[0][2]
            last = b_last / j_last
            said.append(f"{name}: {_pct(points[0][1], points[0][2])} on {points[0][0]}, {_pct(b_last, j_last)} on "
                        f"{d_last}" + (" (down)" if last < first else " (up)" if last > first else ""))
    svg = (f'<div class="chart-scroll"><svg class="chart-svg" viewBox="0 0 {width} {height}" role="group" '
           f'aria-label="Share of judged offers that don\'t match their listing, by sheet">{grid}{ticks}'
           f'{"".join(lines)}</svg></div>')
    return _figure("Offers that don't match their listing, week by week", "; ".join(said) + ".", svg,
                   _legend(legend) if len(legend) > 1 else "",
                   ["Market", "Sheet of", "Don't match", "Judged", "Share"], table)


def categories_chart(market: str, rows: Sequence[Dict[str, Any]]) -> str:
    """Ranked bars: the share of judged offers that don't match their listing, by kind of job, with every judged
    offer together (small kinds included) as a grey bar among them."""
    every_kind = by_category(rows)
    found = [c for c in every_kind if c["judged"] >= MIN_GROUP]
    if len(found) < 3:
        return ""
    bad, judged = sum(c["bad"] for c in every_kind), sum(c["judged"] for c in every_kind)
    every = {"label": "Every kind together", "bad": bad, "judged": judged, "all": True}
    ordered = sorted(found + [every], key=lambda c: -c["bad"] / c["judged"])
    top = max(c["bad"] / c["judged"] for c in ordered) or 1
    name = MARKET_NAMES.get(market, market)
    out = []
    for c in ordered:
        share = c["bad"] / c["judged"]
        cls = "bar s0" if c.get("all") else f"bar s{MARKET_SLOT.get(market, 1)}"
        out.append(f'<div class="bar-row{" bar-all" if c.get("all") else ""}"><span class="bar-name">{e(c["label"])}'
                   f'</span><span class="bar-track">'
                   + _mark("span", cls, f"width:{88 * share / top:.2f}%", f"{_pct(c['bad'], c['judged'])} · "
                           f"{c['bad']:,} of {c['judged']:,}", f"{name}, {c['label'].lower()}")
                   + f'<span class="bar-val">{_pct(c["bad"], c["judged"])}</span></span></div>')
    most, least = found[0], found[-1]
    sentence = (f"{most['label']} offers differ from their listing most often ({_pct(most['bad'], most['judged'])}), "
                f"{least['label'].lower()} least ({_pct(least['bad'], least['judged'])}); across every kind, "
                f"{_pct(bad, judged)}.")
    return _figure(f"{name}: offers that don't match their listing, by kind of job", sentence,
                   f'<div class="bars">{"".join(out)}</div>', "",
                   ["Kind of job", "Don't match", "Judged", "Share"],
                   [[c["label"], f"{c['bad']:,}", f"{c['judged']:,}", _pct(c["bad"], c["judged"])] for c in ordered],
                   note=f"Kinds of job with at least {MIN_GROUP} judged offers. A difference can mean the listing is "
                        "out of date; it is counted, not held against anyone.")


def _columns(groups: Sequence[Tuple[str, Sequence[Tuple[int, str, int, int, str]]]]) -> str:
    """Columns grouped by band: (band, [(slot, series, count, whole, label for the hover)])."""
    top = max((n / whole for _, cols in groups for _, _, n, whole, _ in cols if whole), default=0) or 1
    out = []
    for band, cols in groups:
        bars = "".join(
            f'<span class="col">'
            f'<span class="col-val">{_short(_pct(n, whole, 0)) if len(cols) > 1 else f"{n:,}"}</span>'
            + _mark("span", f"col-bar s{slot}", f"height:{COLUMN_TOP * (n / whole) / top:.2f}%",
                    f"{n:,} · {_pct(n, whole)}", f"{series}, {hover}")
            + "</span>" for slot, series, n, whole, hover in cols)
        out.append(f'<div class="col-group"><div class="col-bars">{bars}</div><span class="col-name">{e(band)}</span>'
                   f"</div>")
    return f'<div class="cols">{"".join(out)}</div>'


def markup_chart(market: str, rows: Sequence[Dict[str, Any]]) -> str:
    """Columns: of the offers that asked more than their listing, how many times more."""
    found = markups(rows)
    if len(found) < MIN_GROUP:
        return ""
    name = MARKET_NAMES.get(market, market)
    counted = bands(found, MARKUP_BANDS)
    slot = MARKET_SLOT.get(market, 1)
    double = sum(1 for v in found if v >= 2)
    tenfold = sum(1 for v in found if v >= 10)
    sentence = (f"Of {len(found):,} offers that asked more than their listing, half asked no more than "
                f"{_times(median(found))} the listed price; {double:,} asked at least twice as much and {tenfold:,} at "
                f"least ten times, up to {_times(max(found))}.")
    chart = _columns([(band, [(slot, name, n, len(found), f"asked {band} the listed price")]) for band, n in counted])
    return _figure(f"{name}: how much more, when an offer asks more than its listing", sentence, chart, "",
                   ["Asked, times the listed price", "Offers", "Share"],
                   [[band, f"{n:,}", _pct(n, len(found))] for band, n in counted],
                   note="Each offer is set beside the listed option for the same network and asset; the largest "
                        "ratio counts.")


def prices_chart(sheets: Dict[str, Dict[str, Any]]) -> str:
    """Grouped columns: each market's payable offers by price band, as shares of that market's priced offers."""
    found = {m: prices(m, s["rows"]) for m, s in sheets.items()}
    found = {m: v for m, v in found.items() if len(v) >= MIN_GROUP}
    if not found:
        return ""
    counted = {m: bands(v, PRICE_BANDS) for m, v in found.items()}
    groups = [(label, [(MARKET_SLOT.get(m, 3), MARKET_NAMES.get(m, m), counted[m][i][1], len(found[m]),
                        f"asks {label}") for m in found]) for i, (_, label) in enumerate(PRICE_BANDS)]
    said = [f"{MARKET_NAMES.get(m, m)} {_usd(median(v))}" for m, v in found.items()]
    sentence = ("What a typical call costs, the median of the offers: " + ", ".join(said) + ".")
    legend = _legend([(MARKET_SLOT.get(m, 3), MARKET_NAMES.get(m, m)) for m in found]) if len(found) > 1 else ""
    rows = [[MARKET_NAMES.get(m, m), label, f"{n:,}", _pct(n, len(found[m]))] for m in found for label, n in counted[m]]
    title = "What one call costs" + ("" if len(found) > 1 else f" on {MARKET_NAMES.get(next(iter(found)), '')}")
    return _figure(title, sentence, _columns(groups), legend, ["Market", "Price of one call", "Offers", "Share"],
                   rows, note="Payable offers that name a price in USDC or a dollar currency, priced as the fair pick "
                              "prices them: the cheapest option an offer names.")


def _day(body: Dict[str, Any]) -> str:
    """The sheet's day from its id (x402-2026-11-16), else its id."""
    tail = str(body.get("id") or "")[-10:]
    try:
        return date.fromisoformat(tail).isoformat()
    except ValueError:
        return str(body.get("id") or "")


SCRIPT = """<script>
(function () {
  var tip = document.createElement("div"), v = document.createElement("strong"), l = document.createElement("span");
  tip.className = "chart-tip"; tip.hidden = true; tip.append(v, l); document.body.append(tip);
  function show(m, x, y) {
    v.textContent = m.getAttribute("data-v"); l.textContent = m.getAttribute("data-l"); tip.hidden = false;
    tip.style.left = Math.max(8, Math.min(window.innerWidth - tip.offsetWidth - 8, x + 14)) + "px";
    tip.style.top = Math.max(8, y - tip.offsetHeight - 12) + "px";
  }
  document.querySelectorAll(".chart [data-v]").forEach(function (m) {
    m.addEventListener("pointermove", function (ev) { show(m, ev.clientX, ev.clientY); });
    m.addEventListener("pointerleave", function () { tip.hidden = true; });
    m.addEventListener("focus", function () {
      var r = m.getBoundingClientRect(); show(m, r.left + r.width / 2, r.top);
    });
    m.addEventListener("blur", function () { tip.hidden = true; });
  });
})();
</script>"""


def section(sheet_entries: Sequence[Dict[str, Any]], loaded: Dict[str, Dict[str, Any]]) -> str:
    """The charts for the page: `sheet_entries` are every sheet entry in the book, oldest first; `loaded` the
    newest sheet of each market whose rows could be read and matched the book (a market missing from it gets only
    the charts its book entry's counts can draw)."""
    newest: Dict[str, Dict[str, Any]] = {}
    for x in sheet_entries:
        newest[sheet_lib.market_of(x["body"])] = x["body"]
    order = sorted(newest, key=lambda m: MARKET_SLOT.get(m, 9))
    figures = [answers_chart({m: newest[m] for m in order}),
               prices_chart({m: loaded[m] for m in order if m in loaded}),
               trend_chart(sheet_entries)]
    for m in order:
        if m in loaded:
            figures += [categories_chart(m, loaded[m]["rows"]), markup_chart(m, loaded[m]["rows"])]
    figures = [f for f in figures if f]
    if not figures:
        return ""
    return ("<h2>The market at a glance</h2>\n<p>Drawn from the newest sheets: from the counts the book signs, and "
            "from the sheets' rows, whose hashes the book signs. Each chart's figures are in the table under it.</p>\n"
            + "".join(figures) + SCRIPT + "\n")
