"""The check before signing: a reading that looks broken is held for the operator, unpublished."""

import functools
import json

from agoranome_inspector import measure
from agoranome_inspector.book import Book
from agoranome_inspector.checks import before_signing
from agoranome_inspector.cli import main

from fakes import down, standard_market


def sheet(answers, complete=True, rows=None):
    return {"selection": {"index_complete": complete},
            "summary": {"rows": sum(answers.values()) if rows is None else rows, "answer": answers}}


NORMAL = {"payable": 96, "gone": 2, "unreachable": 2}


def test_a_normal_week_passes():
    assert before_signing(sheet(NORMAL)) == []
    assert before_signing(sheet({"payable": 90, "gone": 5, "unreachable": 5}), sheet(NORMAL)) == []


def test_each_bound_holds():
    assert before_signing(sheet(NORMAL, complete=False)) == ["the index was not read completely"]
    assert before_signing(sheet({}, rows=0)) == ["the sheet has no rows"]
    assert "gave no answer at all" in before_signing(sheet({"payable": 70, "unreachable": 30}))[0]
    assert "row count moved" in before_signing(sheet({"payable": 60}), sheet(NORMAL))[0]
    assert "payable share moved" in before_signing(sheet({"payable": 80, "gone": 20}), sheet(NORMAL))[0]


def test_not_asked_and_declined_do_not_count_as_unreachable():
    assert before_signing(sheet({"payable": 50, "not_asked": 40, "declined": 5, "unreachable": 5})) == []


def test_a_held_sheet_is_not_published_until_the_operator_says(tmp_path, monkeypatch, capsys):
    market = standard_market()
    monkeypatch.setattr(measure, "IndexReader", lambda: market.reader())
    monkeypatch.setattr(measure, "SafeFetcher", lambda: market.fetcher())
    monkeypatch.setattr(measure, "Settings", functools.partial(measure.Settings, retry_pause=0, confirm_pause=0,
                                                               host_pause=0))
    key = tmp_path / "key.pem"
    assert main(["keygen", "--out", str(key)]) == 0
    site, private = tmp_path / "site", tmp_path / "private"
    run = ["run", str(site), "--private", str(private), "--key-file", str(key), "--concurrency", "4"]
    assert main(run + ["--id", "x402-2026-11-16"]) == 0
    book = Book(str(site / "book.jsonl"))
    before = len(book.entries())
    for host in list(market.sellers):
        market.sellers[host] = down()                 # the run's own network is broken this week
    capsys.readouterr()
    assert main(run + ["--id", "x402-2026-11-23"]) == 3
    out = capsys.readouterr()
    assert json.loads(out.out)["held"] and "HELD, not published" in out.err
    assert (private / "held-x402-2026-11-23.json").exists()
    assert len(book.entries()) == before and not (site / "sheets" / "x402-2026-11-23.json").exists()
    assert main(run + ["--id", "x402-2026-11-23", "--publish-anyway"]) == 0
    entries = book.entries()
    assert [e["kind"] for e in entries[before:]] == ["sheet", "changes", "links", "note"]
    assert entries[-1]["body"]["text"].startswith("Published past the check before signing")
    assert main(["verify", str(site), "--all"]) == 0
