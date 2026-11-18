"""pick-2, the public rule since 18 Nov 2026: fit before price, each word once, two places a seller, over the same
signed pick tables pick-1 ranks. The Agoranome Lab's copy is pinned to these answers (its tests/fixtures)."""

import json

from agoranome_inspector import pick, sellers
from agoranome_inspector.cli import main
from agoranome_inspector.mcp_stdio import Inspector, handle

from test_pick import published_site


def _row(resource, host, words, price, pay_to=None, honest=0, delivery=1):
    return {"resource": resource, "market": "x402", "url": resource, "method": "GET", "host": host,
            "category": "other", "price_usd": price, "honest": honest, "delivery": delivery,
            "pay": {"scheme": "exact", "network": "eip155:8453", "pay_to": pay_to or "0x" + host[:4].encode().hex()},
            "words": pick.tokens(words)}


SPECIALISTS = [
    _row("https://pdf.example/md", "pdf.example", "convert pdf documents to clean markdown", "0.01"),
    _row("https://wx.example/now", "wx.example", "weather forecast for any city hourly", "0.005"),
    _row("https://srch.example/web", "srch.example", "web search results news pages", "0.01"),
] + [_row(f"https://filler{i}.example/x", f"filler{i}.example", f"token balance chain data wallet {i}", "0.002",
          pay_to=f"0x{i:040x}") for i in range(30)]
JOBS = ("convert a pdf to markdown", "weather forecast for a city", "web search for news")


def test_pick_2_ranks_fit_before_price_so_a_cheap_stuffed_listing_does_not_win_every_job():
    stuffed = _row("https://stuff.example/all", "stuff.example",
                   "convert pdf markdown weather forecast city web search news", "0.001")
    tables = [{"market": "x402", "rows": SPECIALISTS + [stuffed]}]
    for job in JOBS:
        assert pick.rank(tables, job)["picked"][0]["host"] == "stuff.example", job   # pick-1
        found = pick.rank2(tables, job)
        assert found["picked"][0]["host"] != "stuff.example", job
        assert found["picked"][0]["fit"] == 1.0 and found["rule"] == "pick-2"
        assert found["rule_text"] == pick.RULE2_TEXT
    # A word said five times counts once.
    plain = _row("https://a.example/wx", "a.example", "weather forecast city", "0.002")
    shouted = _row("https://b.example/wx", "b.example", "weather weather weather weather weather forecast city",
                   "0.002")
    pair = [{"market": "x402", "rows": [plain, shouted] + SPECIALISTS}]
    assert pick.rank(pair, "weather forecast")["picked"][0]["host"] == "b.example"
    scores = {p["host"]: p["match"] for p in pick.rank2(pair, "weather forecast")["picked"]}
    assert scores["a.example"] == scores["b.example"]


def test_pick_2_gives_one_seller_two_places_and_counts_the_rest():
    clones = [_row(f"https://cheap.example/{i}", "cheap.example", "convert pdf to markdown", "0.001",
                   pay_to="0x" + "c" * 40) for i in range(10)]
    tables = [{"market": "x402", "rows": SPECIALISTS + clones}]
    assert [p["host"] for p in pick.rank(tables, "convert a pdf to markdown")["picked"]] == ["cheap.example"] * 10
    found = pick.rank2(tables, "convert a pdf to markdown")
    assert [p["host"] for p in found["picked"]] == ["cheap.example", "cheap.example", "pdf.example"]
    assert [p["more_from_seller"] for p in found["picked"]] == [8, 8, 0]
    assert found["left_out"]["same_seller"] == 8 and found["in_running"] == 11
    # Hosts paid to one wallet that few hosts list are one seller; a pay-to six hosts list is a platform's.
    shared = [_row(f"https://m{i}.example/x", f"m{i}.example", "convert pdf to markdown", "0.001",
                   pay_to="0x" + "d" * 40) for i in range(4)]
    found = pick.rank2([{"market": "x402", "rows": SPECIALISTS + shared}], "convert a pdf to markdown")
    assert [p["host"] for p in found["picked"]] == ["m0.example", "m1.example", "pdf.example"]
    assert {p["seller"] for p in found["picked"][:2]} == {"m0.example"}
    platform = [_row(f"https://p{i}.example/x", f"p{i}.example", "convert pdf to markdown", "0.001",
                     pay_to="0x" + "e" * 40) for i in range(6)]
    found = pick.rank2([{"market": "x402", "rows": SPECIALISTS + platform}], "convert a pdf to markdown")
    assert [p["host"] for p in found["picked"]][:6] == [f"p{i}.example" for i in range(6)]
    assert found["left_out"]["same_seller"] == 0


def test_a_registrable_domain_is_one_seller_and_a_shared_platform_is_not():
    rows = [{"host": "api.acme.com", "pay": {"pay_to": "0x1"}}, {"host": "staging.acme.com", "pay": {"pay_to": "0x2"}},
            {"host": "a.workers.dev", "pay": {"pay_to": "0x3"}}, {"host": "b.workers.dev", "pay": {"pay_to": "0x4"}},
            {"host": "x.acme.co.uk", "pay": {"pay_to": "0x5"}}, {"host": "y.acme.co.uk", "pay": {"pay_to": "0x6"}},
            {"host": "1-2-3-4.sslip.io", "pay": {"pay_to": "0x7"}}, {"host": "5-6-7-8.sslip.io", "pay": {"pay_to": "0x8"}}]
    found = sellers.seller_of(rows, lambda r: r["host"], lambda r: r["pay"]["pay_to"])
    assert found["staging.acme.com"] == found["api.acme.com"] == "api.acme.com"
    assert found["a.workers.dev"] != found["b.workers.dev"]
    assert found["x.acme.co.uk"] == found["y.acme.co.uk"]
    assert found["1-2-3-4.sslip.io"] != found["5-6-7-8.sslip.io"]
    assert sellers.registrable("10.0.0.1") is None and sellers.registrable("api.acme.com") == "acme.com"


def test_the_rule_is_named_and_an_unknown_one_refused():
    tables = [{"market": "x402", "rows": SPECIALISTS}]
    assert pick.rank_by("pick-2", tables, "weather forecast")["rule"] == "pick-2"
    assert pick.rank_by("pick-1", tables, "weather forecast")["rule"] == "pick-1"
    assert pick.RULES[0] == pick.RULE2
    try:
        pick.rank_by("pick-9", tables, "weather")
    except ValueError as e:
        assert "pick-2 or pick-1" in str(e)
    else:
        raise AssertionError("an unknown rule was ranked")


def test_the_command_and_the_mcp_tool_rank_by_pick_2_unless_asked_for_pick_1(tmp_path, monkeypatch, capsys):
    site, kid = published_site(tmp_path, monkeypatch, capsys)
    assert main(["pick", str(site), "web search for an agent", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rule"] == "pick-2"
    assert main(["pick", str(site), "web search for an agent", "--rule", "pick-1", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rule"] == "pick-1"
    assert main(["pick", str(site), "web search"]) == 0
    assert "Fair pick (pick-2)" in capsys.readouterr().out
    inspector = Inspector(str(site), pinned_kid=kid)
    tools = handle(inspector, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    fair = next(t for t in tools if t["name"] == "fair_pick")
    assert fair["inputSchema"]["properties"]["rule"]["enum"] == ["pick-2", "pick-1"]
    for rule in ("pick-2", "pick-1"):
        called = handle(inspector, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "fair_pick", "arguments": {"job": "web search", "rule": rule}}})["result"]
        assert not called["isError"] and called["structuredContent"]["rule"] == rule
    assert "<code>pick-2</code>" in (site / "index.html").read_text()
