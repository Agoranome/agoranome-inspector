"""Charts on the open sheet (Shariar, 11 Nov 2026: "inspector sheet, should include insightful visualizations";
then "use softer colors" and "use more than bar chart").

Each chart is drawn from the newest sheet of each market: from the counts its book entry signs, or from its rows, read
from the site only after their hash matches the book (publish.load_sheet). Each says in one sentence what it shows,
and each keeps its figures in a table under it, so nothing is read from color or hover alone.

  answers     a ring per market: what its endpoints answered, the payable share in the middle, each part named beside
  prices      what one call costs: for each market, the share of payable offers that cost at most each price, on a
              log scale, with the middle price marked
  trend       the share of judged offers that don't match their listing, sheet by sheet, once a market has two
  categories  that share by kind of job: a dot per kind on one scale, with every kind together as a dashed line
  markup      when an offer asks more than its listing, how many times more: four figures, and one square per offer
              shaded by band (like-for-like options only)

A chart needs at least MIN_GROUP offers behind it (the home page's rule for a finding), so no picture is drawn from a
handful. Rings, curves and lines are SVG that scales to the page; dots and squares are plain HTML sized in percent, so
everything fits a phone. Nothing is fetched from another origin: the style is in style.css and the hover script is
inline.

Colors (theme.CSS, .s1 to .s5) are soft tones chosen for the site's baby blue: baby blue, peach, teal, ochre and
lavender. Checked with the data-viz method's validator on the page's surface (#0f1a26), every pair of the five stays
apart, under normal vision (OKLab delta E at least 17.6) and the common colour-blind simulations (at least 8.6), and
each mark has at least 4.7:1 contrast with the surface. They are lighter and greyer than the method's default band:
that is the softness asked for. A series keeps its slot (x402 is slot 1, MPP slot 2). The markup squares use one peach
hue from muted to bright (.r1 to .r5), checked as an ordered ramp. Text is never colored by its series.
"""

import html
import math
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agoranome_inspector import pick as pick_lib
from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.bestbuy import LABELS

MIN_GROUP = 100
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

MARKUP_BANDS: List[Tuple[Decimal, str]] = [
    (Decimal("1.1"), "less than 1.1×"), (Decimal("1.5"), "1.1 to 1.5×"), (Decimal("2"), "1.5 to 2×"),
    (Decimal("10"), "2 to 10×"), (Decimal("Infinity"), "10× or more"),
]
PRICE_BANDS: List[Tuple[Decimal, str]] = [
    (Decimal("0.001"), "under $0.001"), (Decimal("0.01"), "$0.001 to $0.01"), (Decimal("0.1"), "$0.01 to $0.10"),
    (Decimal("1"), "$0.10 to $1"), (Decimal("Infinity"), "$1 or more"),
]
# The price curves' axis, in powers of ten of a dollar: $0.0001 to $10. A price outside it sits at its edge.
PRICE_AXIS = (-4, 1)
PRICE_TICKS = ["$0.0001", "$0.001", "$0.01", "$0.10", "$1", "$10"]
# Squares in the markup chart: one per offer up to this many, then each square stands for several.
WAFFLE_MAX = 600

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


def _legend(items: Sequence[Tuple[str, str]]) -> str:
    """(class, name) pairs: a swatch in the class's color beside each name."""
    return ('<ul class="chart-legend">' + "".join(f'<li><i class="{cls}"></i>{e(name)}</li>' for cls, name in items)
            + "</ul>")


def _svg(width: int, height: int, label: str, inner: str, cls: str = "chart-svg") -> str:
    return (f'<svg class="{cls}" viewBox="0 0 {width} {height}" role="group" aria-label="{e(label)}">{inner}</svg>')


# --- Charts -----------------------------------------------------------------------------------------------------

def _ring(name: str, parts: List[Tuple[str, str, int]], whole: int) -> str:
    """One market's ring: an arc per part in the fixed order from twelve o'clock, a 2px gap between arcs, the
    payable share in the middle, and each part named with its share beside the ring."""
    size, r, centre = 150, 58, 75
    around = 2 * math.pi * r
    shown = [(slot, label, n) for slot, (_, label, n) in enumerate(parts, start=1) if n]
    gap = 2.0 if len(shown) > 1 else 0.0
    arcs, start = [], 0.0
    for slot, label, n in shown:
        length = around * n / whole
        drawn = max(length - gap, 1.0)
        arcs.append(_mark("circle", f"arc s{slot}", "", f"{n:,} · {_pct(n, whole)}", f"{name}: {label.lower()}",
                          attrs=f'cx="{centre}" cy="{centre}" r="{r}" stroke-dasharray="{drawn:.2f} '
                                f'{around - drawn:.2f}" stroke-dashoffset="{-start:.2f}" '
                                f'transform="rotate(-90 {centre} {centre})"'))
        start += length
    payable = parts[0][2]
    middle = (f'<text class="ring-big" x="{centre}" y="{centre + 4}" text-anchor="middle">'
              f'{e(_pct(payable, whole, 0))}</text><text class="ring-small" x="{centre}" y="{centre + 22}" '
              f'text-anchor="middle">payable</text>')
    ring = _svg(size, size, f"{name}: what {whole:,} endpoints answered", "".join(arcs) + middle, "ring-svg")
    parts_list = "".join(f'<li><i class="s{slot}"></i><span>{e(label)}</span><b>{e(_pct(n, whole))}</b></li>'
                         for slot, label, n in shown)
    return (f'<div class="ring"><div class="ring-head"><b>{e(name)}</b><span>{whole:,} endpoints</span></div>'
            f'<div class="ring-body">{ring}<ul class="ring-parts">{parts_list}</ul></div></div>')


def answers_chart(newest: Dict[str, Dict[str, Any]]) -> str:
    """A ring per market: what its endpoints answered."""
    rings, table, said = [], [], []
    for market, body in newest.items():
        parts = answer_parts(body["summary"])
        whole = sum(n for _, _, n in parts)
        if whole < MIN_GROUP:
            continue
        name = MARKET_NAMES.get(market, market)
        rings.append(_ring(name, parts, whole))
        table += [[name, label, f"{n:,}", _pct(n, whole)] for _, label, n in parts if n]
        said.append(f"{name}: {_pct(parts[0][2], whole, 0)}" + ("" if said else " gave an offer an agent can pay"))
    if not rings:
        return ""
    return _figure("What the endpoints answered", "; ".join(said) + ".", f'<div class="rings">{"".join(rings)}</div>',
                   "", ["Market", "Answer", "Endpoints", "Share"], table)


def _log_x(price: Decimal, left: float, width: float) -> float:
    low, high = PRICE_AXIS
    power = math.log10(float(price)) if price > 0 else low
    return left + width * (min(max(power, low), high) - low) / (high - low)


def prices_chart(sheets: Dict[str, Dict[str, Any]]) -> str:
    """Curves: for each market, the share of payable offers that cost at most each price (a log scale from $0.0001
    to $10), the middle price marked with a dot and named."""
    found = {m: sorted(prices(m, s["rows"])) for m, s in sheets.items()}
    found = {m: v for m, v in found.items() if len(v) >= MIN_GROUP}
    if not found:
        return ""
    width, height, left, right, top, bottom = 640, 270, 46, 20, 16, 36
    plot_w, plot_h = width - left - right, height - top - bottom

    def y(share: float) -> float:
        return top + plot_h * (1 - share)

    low, high = PRICE_AXIS
    grid = "".join(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="tick" x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{t * 100:.0f}%</text>'
                   for t in (0, 0.25, 0.5, 0.75, 1))
    grid += "".join(f'<line class="grid grid-v" x1="{left + plot_w * i / (high - low):.1f}" '
                    f'x2="{left + plot_w * i / (high - low):.1f}" y1="{top}" y2="{top + plot_h}"/>'
                    f'<text class="tick" x="{left + plot_w * i / (high - low):.1f}" y="{height - 12}" '
                    f'text-anchor="middle">{e(t)}</text>' for i, t in enumerate(PRICE_TICKS))
    grid += (f'<line class="ref" x1="{left}" x2="{width - right}" y1="{y(0.5):.1f}" y2="{y(0.5):.1f}"/>'
             f'<text class="ref-label" x="{width - right}" y="{y(0.5) - 6:.1f}" text-anchor="end">half the offers'
             f'</text>')
    curves, legend, said, table, beyond = [], [], [], [], []
    for i, (m, values) in enumerate(found.items()):
        slot, name, n = MARKET_SLOT.get(m, 3), MARKET_NAMES.get(m, m), len(values)
        steps = Counter(values)
        path, seen = [f"M{left},{y(0):.1f}"], 0
        for price in sorted(steps):
            seen += steps[price]
            path.append(f"H{_log_x(price, left, plot_w):.1f}V{y(seen / n):.1f}")
        path.append(f"H{width - right}")
        mid = median(values)
        at_most = {t: sum(1 for v in values if v <= Decimal(t[1:])) for t in PRICE_TICKS[1:-1]}
        dots = "".join(_mark("circle", f"dot dot-s s{slot}", "", f"{_pct(k, n)} cost at most {t}", name,
                             attrs=f'cx="{_log_x(Decimal(t[1:]), left, plot_w):.1f}" cy="{y(k / n):.1f}" r="3.5"')
                       for t, k in at_most.items())
        mx = _log_x(mid, left, plot_w)
        dots += _mark("circle", f"dot s{slot}", "", f"half cost at most {_usd(mid)}", f"{name}, the middle price",
                      attrs=f'cx="{mx:.1f}" cy="{y(0.5):.1f}" r="6"')
        # The middle prices' names sit on either side of the half line, so two never collide.
        above = i % 2 == 0
        curves.append(f'<path class="line s{slot}" d="{"".join(path)}"/>{dots}'
                      f'<text class="end" x="{mx + (-10 if above else 10):.1f}" '
                      f'y="{y(0.5) + (-12 if above else 22):.1f}" text-anchor="{"end" if above else "start"}">'
                      f'{e(name)} {e(_usd(mid))}</text>')
        legend.append((f"s{slot}", name))
        said.append(f"half of {name}'s payable offers cost at most {_usd(mid)} a call" if not said
                    else f"half of {name}'s, at most {_usd(mid)}")
        running = 0
        for label, k in bands(values, PRICE_BANDS):
            running += k
            table.append([name, label, f"{k:,}", _pct(k, n), _pct(running, n)])
        over = sum(1 for v in values if v > Decimal(10) ** high)
        if over:
            beyond.append(f"{over:,} of {name}'s")
    svg = _svg(width, height, "Share of payable offers that cost at most each price", grid + "".join(curves))
    sentence = "; ".join(said) + "."
    title = "What one call costs" + ("" if len(found) > 1 else f" on {MARKET_NAMES.get(next(iter(found)), '')}")
    return _figure(title, sentence[0].upper() + sentence[1:], f'<div class="chart-scroll">{svg}</div>',
                   _legend(legend) if len(legend) > 1 else "",
                   ["Market", "Price of one call", "Offers", "Share", "At most this band"], table,
                   note="Each curve climbs as the price rises: the share of a market's payable offers that cost at "
                        "most that much. Payable offers that name a price in USDC or a dollar currency, priced as "
                        "the fair pick prices them: the cheapest option an offer names."
                        + (f" Past the right edge, over $10: {' and '.join(beyond)}." if beyond else ""))


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
        legend.append((f"s{slot}", name))
        if len(points) >= 2:
            first = points[0][1] / points[0][2]
            last = b_last / j_last
            said.append(f"{name}: {_pct(points[0][1], points[0][2])} on {points[0][0]}, {_pct(b_last, j_last)} on "
                        f"{d_last}" + (" (down)" if last < first else " (up)" if last > first else ""))
    svg = _svg(width, height, "Share of judged offers that don't match their listing, by sheet",
               grid + ticks + "".join(lines))
    return _figure("Offers that don't match their listing, week by week", "; ".join(said) + ".",
                   f'<div class="chart-scroll">{svg}</div>', _legend(legend) if len(legend) > 1 else "",
                   ["Market", "Sheet of", "Don't match", "Judged", "Share"], table)


def categories_chart(market: str, rows: Sequence[Dict[str, Any]]) -> str:
    """A dot plot: the share of judged offers that don't match their listing, one dot per kind of job on a common
    scale, most first, with every judged offer together (small kinds included) as a dashed line across them."""
    every_kind = by_category(rows)
    found = [c for c in every_kind if c["judged"] >= MIN_GROUP]
    if len(found) < 3:
        return ""
    bad, judged = sum(c["bad"] for c in every_kind), sum(c["judged"] for c in every_kind)
    top = max(c["bad"] / c["judged"] for c in found)
    ceiling = next((c / 100 for c in (5, 10, 15, 20, 25, 30, 40, 50, 75) if top <= c / 100), 1.0)
    name, slot = MARKET_NAMES.get(market, market), MARKET_SLOT.get(market, 1)

    def at(share: float) -> str:
        return f"{100 * share / ceiling:.2f}%"

    out = []
    for c in found:
        share = c["bad"] / c["judged"]
        out.append(f'<div class="dot-row"><span class="dot-name">{e(c["label"])}</span><span class="dot-track">'
                   f'<i class="stem" style="width:{at(share)}"></i>'
                   + _mark("span", f"pin s{slot}", f"left:{at(share)}", f"{_pct(c['bad'], c['judged'])} · "
                           f"{c['bad']:,} of {c['judged']:,}", f"{name}, {c['label'].lower()}")
                   + f'<span class="dot-val" style="left:{at(share)}">{_pct(c["bad"], c["judged"])}</span>'
                   f'</span></div>')
    step = next(t for t in (1, 2, 2.5, 5, 10, 20, 25, 50) if ceiling * 100 / t <= 6)
    ticks = "".join(f'<b style="left:{at(i * step / 100)}">{i * step:g}%</b>'
                    for i in range(int(round(ceiling * 100 / step)) + 1))
    axis = (f'<div class="dot-row dot-axis"><span class="dot-name"></span><span class="dot-track">{ticks}'
            f'<em style="left:{at(bad / judged)}">all kinds {e(_pct(bad, judged))}</em></span></div>')
    most, least = found[0], found[-1]
    sentence = (f"{most['label']} offers differ from their listing most often ({_pct(most['bad'], most['judged'])}), "
                f"{least['label'].lower()} least ({_pct(least['bad'], least['judged'])}); across every kind, "
                f"{_pct(bad, judged)}.")
    every = {"label": "Every kind together", "bad": bad, "judged": judged}
    return _figure(f"{name}: offers that don't match their listing, by kind of job", sentence,
                   f'<div class="dots" style="--ref:{at(bad / judged)}">{"".join(out)}{axis}</div>', "",
                   ["Kind of job", "Don't match", "Judged", "Share"],
                   [[c["label"], f"{c['bad']:,}", f"{c['judged']:,}", _pct(c["bad"], c["judged"])]
                    for c in found + [every]],
                   note=f"Kinds of job with at least {MIN_GROUP} judged offers; the dashed line is every judged "
                        "offer together. A difference can mean the listing is out of date; it is counted, not held "
                        "against anyone.")


def markup_chart(market: str, rows: Sequence[Dict[str, Any]]) -> str:
    """Four figures and a square per offer: of the offers that asked more than their listing, how many times more,
    the squares shaded from muted (a little more) to bright (ten times or more)."""
    found = markups(rows)
    if len(found) < MIN_GROUP:
        return ""
    name = MARKET_NAMES.get(market, market)
    counted = bands(found, MARKUP_BANDS)
    n, middle = len(found), median(found)
    double, tenfold = sum(1 for v in found if v >= 2), sum(1 for v in found if v >= 10)
    tiles = [(f"{n:,}", "offers asked more than their listing"),
             (_times(middle), "the middle one asked, times its listed price"),
             (f"{double:,}", "asked at least twice as much"),
             (f"{tenfold:,}", f"asked ten times or more, up to {_times(max(found))}")]
    tiles_html = ('<div class="tiles">' + "".join(f'<div class="tile"><b>{e(big)}</b><span>{e(small)}</span></div>'
                                                  for big, small in tiles) + "</div>")
    per = max(1, math.ceil(n / WAFFLE_MAX))
    cells = []
    for i, (band, k) in enumerate(counted, start=1):
        squares = 0 if not k else max(1, round(k / per))
        cells.append(f'<i class="r{i}" data-v="{e(band)}" data-l="{k:,} offers ({e(_pct(k, n))})"></i>' * squares)
    waffle = (f'<div class="waffle" role="img" aria-label="{n:,} offers, '
              + ("one square each" if per == 1 else f"one square for every {per}")
              + f', shaded by how many times their listed price they asked">{"".join(cells)}</div>')
    legend = _legend([(f"r{i}", f"{band}: {k:,}") for i, (band, k) in enumerate(counted, start=1)])
    sentence = (f"Of {n:,} offers that asked more than their listing, half asked no more than {_times(middle)} the "
                f"listed price; {double:,} asked at least twice as much and {tenfold:,} at least ten times.")
    return _figure(f"{name}: how much more, when an offer asks more than its listing", sentence,
                   tiles_html + waffle, legend, ["Asked, times the listed price", "Offers", "Share"],
                   [[band, f"{k:,}", _pct(k, n)] for band, k in counted],
                   note=("Each square is one offer. " if per == 1 else f"Each square is about {per} offers. ")
                        + "Each offer is set beside the listed option for the same network and asset; the largest "
                          "ratio counts.")


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
