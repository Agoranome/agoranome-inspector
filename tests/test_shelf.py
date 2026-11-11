"""The shelf report card: graded from facts with their sources and the newest sheets, recomputed by the verifier."""

import copy
import json

from agoranome_inspector import shelf
from agoranome_inspector.book import Book, entries_of
from agoranome_inspector.cli import main

from fakes import standard_market


def sheet_body(payable=100, above=5, missing=0, different=3, not_listed=0, varies=0, market="x402"):
    return {"id": f"{market}-2026-11-16", "market": market,
            "summary": {"answer": {"payable": payable, "gone": 4},
                        "price": {"as_listed": payable - above - missing - not_listed - varies, "above_listed": above,
                                  "listed_option_missing": missing, "not_listed": not_listed, "varies": varies},
                        "pay_to": {"as_listed": payable - different, "different": different}}}


def test_matches_is_measured_from_the_sheet_and_graded_by_thresholds():
    assert shelf.measured_match(sheet_body(above=2, different=1))["answer"] == "yes"       # 97 of 100
    found = shelf.measured_match(sheet_body(above=10, different=5))
    assert found["answer"] == "partly" and found["matched"] == 85 and found["share"] == "0.850"
    assert shelf.measured_match(sheet_body(above=30))["answer"] == "no"
    # Prices set by the request and answers that varied are not judged; none at all is unknown.
    assert shelf.measured_match(sheet_body(payable=10, above=0, different=0, not_listed=10))["answer"] == "unknown"
    assert shelf.measured_match(None)["answer"] == "unknown"


def test_each_shelf_is_graded_from_its_facts_and_its_markets_sheet():
    cards = {c["shelf"]: c for c in shelf.card(shelf.FACTS, {"x402": sheet_body(above=2, different=1),
                                                              "mpp": sheet_body(market="mpp", above=20)})}
    assert set(cards) == {"bazaar", "agentcore", "mpp", "skyfire"}
    bazaar = cards["bazaar"]
    # open yes (2), rank partly (1), matches yes (2), delivery no, dispute no: 5 points, C.
    assert (bazaar["points"], bazaar["grade"]) == (5, "C")
    assert bazaar["answers"]["rank"]["source"].startswith("https://") and bazaar["answers"]["rank"]["read"]
    assert cards["skyfire"]["answers"]["matches"]["answer"] == "unknown"           # no Skyfire sheet
    assert cards["skyfire"]["grade"] == "D"
    for c in cards.values():
        assert c["of"] == 10 and set(c["answers"]) == set(shelf.QUESTIONS)


def test_the_weekly_card_goes_in_the_book_when_something_changed_and_verifies(tmp_path, monkeypatch, capsys):
    from agoranome_inspector import measure

    market = standard_market()
    monkeypatch.setattr(measure, "IndexReader", lambda: market.reader())
    monkeypatch.setattr(measure, "SafeFetcher", lambda: market.fetcher())
    key = tmp_path / "key.pem"
    main(["keygen", "--out", str(key)])
    kid = json.loads(capsys.readouterr().out)["kid"]
    site = tmp_path / "site"
    assert main(["run", str(site), "--private", str(tmp_path / "p"), "--key-file", str(key), "--id", "2026-11-16",
                 "--concurrency", "2"]) == 0
    assert main(["shelf", str(site), "--key-file", str(key)]) == 0
    assert main(["shelf", str(site), "--key-file", str(key)]) == 0      # nothing changed: no second entry
    book = Book(str(site / "book.jsonl"))
    assert len(entries_of("shelf", book.entries())) == 1
    published = json.loads((site / "shelves.json").read_text())
    assert published["rule"] == "shelf-1" and {c["shelf"] for c in published["shelves"]} >= {"bazaar", "mpp"}
    assert "The shelves" in (site / "index.html").read_text()
    capsys.readouterr()
    assert main(["verify", str(site), f"--key={kid}", "--json"]) == 0
    checks = json.loads(capsys.readouterr().out)["checks"]
    assert any(c["check"].startswith("shelf") and c["ok"] and "recomputed" in c["detail"] for c in checks)


def test_a_card_that_does_not_follow_from_its_inputs_is_caught():
    entries = [{"seq": 3, "kind": "sheet", "body": sheet_body()}]
    body = shelf.shelf_body(entries)
    assert shelf.check(body, entries) == []
    flattered = copy.deepcopy(body)
    flattered["shelves"][0]["grade"] = "A"
    assert shelf.check(flattered, entries) == ["the shelf card does not follow from its facts and sheets"]
    moved = copy.deepcopy(body)
    moved["sheets"]["x402"]["seq"] = 9
    assert "which the book lacks" in shelf.check(moved, entries)[0]
    assert shelf.check({**body, "rule": "shelf-0"}, entries) == ["unknown shelf rule 'shelf-0'"]
