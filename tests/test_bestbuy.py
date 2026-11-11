"""Best-buy sheets (best-buy-1): each kind of job, price and delivery signs side by side, rebuilt from the book."""

import json

from agoranome_inspector import bestbuy, pledge
from agoranome_inspector.cli import main

from test_signs import fake_rpc, market


def test_best_buy_sheets_join_the_pick_tables_with_signs_and_reports(tmp_path, monkeypatch, capsys):
    from agoranome_inspector import measure

    m = market()
    monkeypatch.setattr(measure, "IndexReader", lambda: m.reader())
    monkeypatch.setattr(measure, "SafeFetcher", lambda: m.fetcher())
    monkeypatch.setattr(pledge, "http_post", fake_rpc(limit=10 ** 9))
    key = tmp_path / "key.pem"
    main(["keygen", "--out", str(key)])
    kid = json.loads(capsys.readouterr().out)["kid"]
    site = tmp_path / "site"
    assert main(["run", str(site), "--private", str(tmp_path / "p"), "--key-file", str(key), "--id", "2026-11-16",
                 "--concurrency", "2"]) == 0
    assert main(["best-buy", str(site), "--key-file", str(key)]) == 0
    capsys.readouterr()
    assert main(["signs", str(site), "--rpc", "https://rpc.example", "--key-file", str(key)]) == 0
    capsys.readouterr()
    assert main(["best-buy", str(site), "--key-file", str(key)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"seq": out["seq"], "categories": 1, "listings": 9, "with_repeat_payers": 1}
    assert main(["best-buy", str(site), "--key-file", str(key)]) == 0
    assert json.loads(capsys.readouterr().out) == {"unchanged": True}
    entries = [json.loads(line) for line in (site / "book.jsonl").read_text().splitlines()]
    newest = [e for e in entries if e["kind"] == "bestbuy"][-1]
    found = json.loads((site / newest["body"]["file"]).read_text())
    web = found["categories"][0]
    assert web["category"] == "web_search" and web["label"] == "Web search"
    first = web["rows"][0]
    # Every seller asked what it lists at the same price, so the order falls to the address; h1's signs show.
    h1 = next(r for r in web["rows"] if r["host"] == "h1.example")
    assert h1["signs"] == {"real_payers": 2, "repeat_payers": 1} and first["resource"] < web["rows"][1]["resource"]
    assert "signs" not in next(r for r in web["rows"] if r["host"] == "p1.example")     # a platform's address
    page = (site / "best-buy" / "index.html").read_text()
    assert "Best buys, by kind of job" in page and "best-buy-1" in page
    assert "Best buys" in (site / "index.html").read_text()
    capsys.readouterr()
    assert main(["verify", str(site), f"--key={kid}", "--json", "--all"]) == 0
    checks = [c for c in json.loads(capsys.readouterr().out)["checks"] if c["check"].startswith("best-buy")]
    assert len(checks) == 2 and all(c["ok"] for c in checks)
    # A row moved by hand no longer rebuilds.
    found["categories"][0]["rows"].reverse()
    assert bestbuy.build([], None, {}, found["sources"]) != found


def test_reports_are_counted_by_resource_and_outcome():
    entries = [{"kind": "reports", "body": {"reports": [{"resource": "https://a.example/x", "outcome": "delivered"},
                                                       {"resource": "https://a.example/x", "outcome": "delivered"},
                                                       {"resource": "https://a.example/x", "outcome": "too_slow"}]}}]
    assert bestbuy.report_counts(entries) == {"https://a.example/x": {"delivered": 2, "too_slow": 1}}
