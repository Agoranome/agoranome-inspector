"""The open sheet's charts (Shariar 2026-11-11: "inspector sheet, should include insightful visualizations", then
"use softer colors" and "use more than bar chart"): each drawn from the book's counts or from a sheet whose hash the
book signs, none from a handful of offers, each with its figures in a table, and none able to stop the page."""

import html
import re
from decimal import Decimal

from agoranome_inspector import charts, publish as publish_lib
from agoranome_inspector.keys import Signer
from agoranome_inspector.publish import publish

from fakes import honest, standard_market
from test_markets import measure


def counts(**answer):
    return {"answer": answer}


def test_answers_fold_into_five_parts_and_an_unknown_answer_counts_as_failed():
    parts = charts.answer_parts(counts(payable=90, wants_input=3, not_asked=2, declined=1, gone=1, http_4xx=1,
                                       http_5xx=1, something_new=1))
    assert [(k, n) for k, _, n in parts] == [("payable", 90), ("wants_input", 3), ("not_asked", 3), ("gone", 2),
                                            ("failed", 2)]


def test_no_chart_from_a_handful():
    body = {"id": "x402-2026-11-16", "summary": counts(payable=60, gone=39)}
    assert charts.answers_chart({"x402": body}) == ""
    body["summary"]["answer"]["gone"] = 40
    assert "What the endpoints answered" in charts.answers_chart({"x402": body})


def test_the_answers_chart_names_each_part_and_keeps_its_figures():
    out = charts.answers_chart({
        "x402": {"id": "x402-2026-11-16", "summary": counts(payable=960, gone=30, http_5xx=10)},
        "mpp": {"id": "mpp-2026-11-16", "summary": counts(payable=42, wants_input=14, not_asked=35, gone=4,
                                                          unreadable_offer=5)},
    })
    assert "x402: 96% gave an offer an agent can pay; MPP: 42%." in out
    # A ring per market: an arc per part there is, the payable share in the middle, each part named beside it.
    assert out.count('class="ring"') == 2 and out.count('class="arc s1"') == 2 and out.count('class="arc s2"') == 1
    assert '>96%</text><text class="ring-small"' in out and '>42%</text><text class="ring-small"' in out
    x402 = re.search(r'<b>x402</b>.*?</ul>', out).group(0)
    named = re.findall(r"<li><i class=\"s\d\"></i><span>(.*?)</span><b>(.*?)</b></li>", x402)
    assert named == [("Gave an offer an agent can pay", "96%"), ("Gone or refused", "3%"),
                     ("Failed, or gave no usable offer", "1%")]
    # The arcs go round once: their lengths and the gaps between them add up to the whole circle.
    dashes = [tuple(map(float, d.split())) for d in re.findall(r'stroke-dasharray="([\d. ]+)"', x402)]
    assert {round(a + b, 1) for a, b in dashes} == {round(2 * 3.141592653589793 * 58, 1)}
    assert "<td>x402</td><td>Gone or refused</td><td>30</td><td>3%</td>" in out


def test_shares_never_round_to_nothing_or_to_everything():
    assert charts._pct(8, 5487, 0) == "under 1%"
    assert charts._pct(5486, 5487) == "over 99.9%" and charts._pct(10, 10, 0) == "100%"
    assert charts._pct(81, 521) == "15.5%" and charts._pct(0, 10) == "0%" and charts._pct(1, 0) == "0%"


def row(category, matches, answer="payable", price=None, differs=()):
    return {"category": category, "verdict": {"answer": answer, "matches_listing": matches, "price": price,
                                              "differs": list(differs)}}


def test_kinds_of_job_rank_by_their_share_that_doesnt_match(monkeypatch):
    rows = ([row("web_search", False)] * 30 + [row("web_search", True)] * 70
            + [row("news", False)] * 10 + [row("news", True)] * 90
            + [row("chain_data", False)] * 15 + [row("chain_data", True)] * 85
            + [row("weather_geo", False)] * 40          # too few judged to stand alone, counted in every kind
            + [row("web_search", None)] * 500)          # not judged, so not counted
    found = charts.by_category(rows)
    assert [(c["category"], c["bad"], c["judged"]) for c in found] == [
        ("weather_geo", 40, 40), ("web_search", 30, 100), ("chain_data", 15, 100), ("news", 10, 100)]
    out = charts.categories_chart("x402", rows)
    # A dot per kind on one scale (30% at the right end), every judged offer together as the dashed line.
    names = re.findall(r'<span class="dot-name">([^<]+)</span>', out)
    assert names == ["Web search", "On-chain data", "News"]
    assert 'class="pin s1" style="left:100.00%"' in out and 'class="pin s1" style="left:33.33%"' in out
    assert 'style="--ref:93.14%"' in out and "all kinds 27.9%" in out
    assert re.findall(r'<b style="left:[\d.]+%">([\d.]+%)</b>', out) == ["0%", "5%", "10%", "15%", "20%", "25%", "30%"]
    assert "Weather" not in out.split("<details")[0]
    assert "<td>Every kind together</td><td>95</td><td>340</td><td>27.9%</td>" in out
    assert "Web search offers differ from their listing most often (30%), news least (10%); across every kind, " \
           "27.9%." in out
    # Fewer than three kinds with enough judged offers: no ranking.
    assert charts.categories_chart("x402", rows[:200]) == ""


def test_a_kind_of_job_is_escaped():
    rows = [row("<b>odd</b>", False)] * 100 + [row("news", True)] * 100 + [row("media", True)] * 100
    out = charts.categories_chart("x402", rows)
    assert "<b>odd</b>" not in out and "&lt;b&gt;odd&lt;/b&gt;" in out


def above(asked, listed, price="above_listed"):
    return {"asked_amount": asked, "listed_amount": listed, "price": price, "network": "base", "asset": "usdc"}


def test_how_much_more_sets_like_beside_like():
    rows = [
        row("news", False, price="above_listed", differs=[above("12000", "10000")]),
        # Two compared options: the larger ratio counts; a missing option and a free listing are not ratios.
        row("news", False, price="above_listed", differs=[above("30000", "10000"), above("11000", "10000"),
                                                          above("5", "0"), {"price": "missing"}]),
        row("news", False, price="as_listed", differs=[above("90000", "10000")]),   # not above, not counted
        row("news", False, price="above_listed", differs=[above("n/a", "10000")]),  # no number, no ratio
    ]
    assert charts.markups(rows) == [Decimal("1.2"), Decimal("3")]
    assert charts.bands([Decimal("1.05"), Decimal("1.1"), Decimal("2"), Decimal("400")], charts.MARKUP_BANDS) == [
        ("less than 1.1×", 1), ("1.1 to 1.5×", 1), ("1.5 to 2×", 0), ("2 to 10×", 1), ("10× or more", 1)]


def test_the_markup_chart_needs_a_hundred_offers_and_says_the_middle():
    rows = ([row("news", False, price="above_listed", differs=[above("12000", "10000")])] * 80
            + [row("news", False, price="above_listed", differs=[above("40000", "10000")])] * 19
            + [row("news", False, price="above_listed", differs=[above("4000000", "10000")])])
    assert charts.markup_chart("x402", rows[:99]) == ""
    out = charts.markup_chart("x402", rows)
    assert "Of 100 offers that asked more than their listing, half asked no more than 1.2×" in out
    assert "20 asked at least twice as much and 1 at least ten times." in out
    # Four figures, then a square per offer, shaded by band in order.
    tiles = re.findall(r'<div class="tile"><b>(.*?)</b><span>(.*?)</span></div>', out)
    assert [t[0] for t in tiles] == ["100", "1.2×", "20", "1"] and tiles[3][1].endswith("up to 400×")
    squares = re.findall(r'<i class="r(\d)" data-v="(.*?)"', re.search(r'<div class="waffle".*?</div>', out).group(0))
    assert len(squares) == 100 and [int(k) for k, _ in squares] == sorted(int(k) for k, _ in squares)
    assert squares.count(("2", "1.1 to 1.5×")) == 80 and squares.count(("5", "10× or more")) == 1
    assert "Each square is one offer." in out and "<td>1.1 to 1.5×</td><td>80</td><td>80%</td>" in out


def test_prices_are_the_fair_picks_and_need_enough_offers(monkeypatch):
    sheet = measure(standard_market(), "x402-2026-11-16")
    assert sorted(charts.prices("x402", sheet["rows"])) == [Decimal("0.001"), Decimal("0.005"), Decimal("0.005"),
                                                             Decimal("0.01")]
    assert charts.prices_chart({"x402": sheet}) == ""
    monkeypatch.setattr(charts, "MIN_GROUP", 4)
    out = charts.prices_chart({"x402": sheet})
    assert "What one call costs on x402" in out
    assert "Half of x402's payable offers cost at most $0.005 a call." in html.unescape(out)
    assert "<td>x402</td><td>$0.001 to $0.01</td><td>3</td><td>75%</td><td>75%</td>" in out
    # One market: a curve with its middle price named, and no legend; the chart's title names the market instead.
    assert 'class="line s1"' in out and ">x402 $0.005</text>" in out and 'class="chart-legend"' not in out
    assert "half cost at most $0.005" in out and "Past the right edge" not in out


def test_the_price_curves_climb_to_every_offer_and_say_what_is_past_the_edge(monkeypatch):
    monkeypatch.setattr(charts, "MIN_GROUP", 2)
    monkeypatch.setattr(charts, "prices", lambda market, rows: [Decimal(v) for v in rows])
    out = charts.prices_chart({"x402": {"rows": ["0.001", "0.01", "0.01", "50"]},
                               "mpp": {"rows": ["0.00001", "0.02"]}})
    text = html.unescape(out)
    assert "Half of x402's payable offers cost at most $0.01 a call; half of MPP's, at most $0.010005." in text
    assert "Past the right edge, over $10: 1 of x402's." in text and 'class="chart-legend"' in out
    # Each curve is a staircase from 0% at the left edge; x402's last offer, past $10, climbs at the right edge.
    x402, mpp = re.findall(r'<path class="line s\d" d="(.*?)"/>', out)
    assert x402 == "M46,234.0H160.8V179.5H275.6V70.5H620.0V16.0H620"
    assert mpp.startswith("M46,234.0H46.0V125.0")


def summary(bad, good):
    return {"matches_listing": {"false": bad, "true": good, "null": 7}, "answer": {"payable": bad + good}}


def test_many_offers_share_a_square(monkeypatch):
    monkeypatch.setattr(charts, "WAFFLE_MAX", 40)
    rows = [row("news", False, price="above_listed", differs=[above("12000", "10000")])] * 99 + [
        row("news", False, price="above_listed", differs=[above("4000000", "10000")])]
    out = charts.markup_chart("x402", rows)
    assert "Each square is about 3 offers." in out and "one square for every 3" in out
    # A band with any offer keeps at least one square.
    waffle = re.search(r'<div class="waffle".*?</div>', out).group(0)
    assert len(re.findall(r'<i class="r2"', waffle)) == 33 and len(re.findall(r'<i class="r5"', waffle)) == 1


def test_the_trend_waits_for_a_second_sheet_and_then_follows_each_market():
    entries = [{"body": {"id": "x402-2026-11-16", "market": "x402", "summary": summary(100, 900)}},
               {"body": {"id": "mpp-2026-11-16", "market": "mpp", "summary": summary(50, 450)}}]
    assert charts.trend_chart(entries) == ""
    entries.append({"body": {"id": "x402-2026-11-23", "market": "x402", "summary": summary(80, 920)}})
    out = charts.trend_chart(entries)
    assert "x402: 10% on 2026-11-16, 8% on 2026-11-23 (down)." in out
    assert out.count('class="line s1"') == 1 and out.count('class="line s2"') == 1
    assert out.count("<circle") == 3 and 'class="chart-legend"' in out
    assert "<td>x402</td><td>2026-11-23</td><td>80</td><td>1,000</td><td>8%</td>" in out


def test_the_page_draws_the_charts_from_the_book_and_the_signed_sheets(tmp_path, monkeypatch):
    monkeypatch.setattr(charts, "MIN_GROUP", 4)
    signer, market = Signer.generate(), standard_market()
    publish(str(tmp_path), measure(market, "x402-2026-11-16"), signer)
    market.sellers["pricey.example"] = honest("5000")
    publish(str(tmp_path), measure(market, "x402-2026-11-23"), signer)
    page = (tmp_path / "index.html").read_text()
    glance = page[page.index("<h2>The market at a glance</h2>"):page.index("<h2>x402: sheet")]
    assert "What the endpoints answered" in glance and "What one call costs on x402" in glance
    assert "x402: 50% on 2026-11-16, 25% on 2026-11-23 (down)." in glance
    # Marks name their figures by hover, focus and label; the script is inline and fetches nothing.
    assert 'tabindex="0" role="img" aria-label="x402: gave an offer an agent can pay: ' in glance
    assert "<script>" in glance and "textContent" in glance and "innerHTML" not in glance
    assert not re.search(r'(src|href)="(https?:)?//', glance) and "fetch(" not in glance
    assert "github.com" not in page


def test_no_glance_from_the_small_fake_market(tmp_path):
    publish(str(tmp_path), measure(standard_market(), "x402-2026-11-16"), Signer.generate())
    page = (tmp_path / "index.html").read_text()
    assert "at a glance" not in page and "<script>" not in page and "x402: sheet x402-2026-11-16" in page


def test_a_sheet_that_doesnt_match_the_book_loses_only_its_row_charts(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(charts, "MIN_GROUP", 4)
    out = publish(str(tmp_path), measure(standard_market(), "x402-2026-11-16"), Signer.generate())
    sheet_file = tmp_path / out["sheet"]["body"]["file"]
    sheet_file.write_bytes(sheet_file.read_bytes().replace(b"honest.example", b"hon3st.example"))
    publish_lib.write_index(tmp_path, publish_lib.Book(str(tmp_path / publish_lib.BOOK)))
    page = (tmp_path / "index.html").read_text()
    assert "What the endpoints answered" in page and "What one call costs" not in page
    err = capsys.readouterr().err
    assert "the x402 sheet's rows were not read (RuntimeError)" in err and "example" not in err


def test_a_chart_that_fails_never_stops_the_page(tmp_path, monkeypatch, capsys):
    def broken(*_):
        raise KeyError("pricey.example")
    monkeypatch.setattr(charts, "section", broken)
    publish(str(tmp_path), measure(standard_market(), "x402-2026-11-16"), Signer.generate())
    assert "The open sheet" in (tmp_path / "index.html").read_text()
    err = capsys.readouterr().err
    assert "charts: left out (KeyError)" in err and "pricey" not in err
