"""A restatement: a published sheet judged again under a newer rule, signed beside it, rebuilt by the verifier."""

import base64
import json

import httpx
import pytest

from agoranome_inspector import changes as changes_lib
from agoranome_inspector import restate as restate_lib
from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.book import Book, entries_of
from agoranome_inspector.cli import main
from agoranome_inspector.keys import Signer
from agoranome_inspector.measure import Settings, ask_all
from agoranome_inspector.publish import publish, restate
from agoranome_inspector.verify import verify

from fakes import Market, item, option

USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
A = "0x1111111111111111111111111111111111111111"
B = "0x2222222222222222222222222222222222222222"
XRP_A = "rA1111111111111111111111111111111"


def usdc(amount, pay_to=A):
    return {"scheme": "exact", "network": "eip155:8453", "asset": USDC, "amount": amount, "pay_to": pay_to}


def xrp(amount):
    return {"scheme": "exact", "network": "xrpl:0", "asset": "XRP", "amount": amount, "pay_to": XRP_A}


def listing(host, listed):
    return {"resource": f"https://{host}/x", "host": host, "category": "other", "listed": listed,
            "payers_30d": 5, "calls_30d": 20}


def answered(*options):
    return {"at": "2026-11-16T06:00:00Z", "attempts": 1, "method": "GET", "status": 402, "where": "header",
            "x402": 2, "options": list(options), "fair_offer": None, "sha256": None, "error": None}


def week(sheet_id, xrp_asked, rule):
    listings = [
        listing("drift.example", [usdc("10000"), xrp("2077")]),
        listing("dear.example", [usdc("10000")]),
        listing("swap.example", [usdc("10000")]),
        listing("honest.example", [usdc("10000")]),
    ]
    seen = {
        "https://drift.example/x": answered(usdc("10000"), xrp(xrp_asked)),
        "https://dear.example/x": answered(usdc("12000")),
        "https://swap.example/x": answered(usdc("10000", pay_to=B)),
        "https://honest.example/x": answered(usdc("10000")),
    }
    index = {"url": "https://index.example", "read_at": "2026-11-16T05:00:00Z", "total_reported": 4,
             "complete": True, "digest": "0x00", "listings": 4}
    return sheet_lib.build(sheet_id, listings, seen, index=index, probe={}, rule=rule)


@pytest.fixture
def site(tmp_path):
    signer = Signer.generate()
    old = week("x402-2026-11-16", "2105", "sheet-1")
    publish(str(tmp_path), old, signer, time="2026-11-16T07:00:00Z")
    return tmp_path, signer, old


def test_sheet_1_counted_the_drift_and_sheet_2_does_not(site):
    _, _, old = site
    assert old["rule"] == "sheet-1" and old["summary"]["matches_listing"] == {"false": 3, "true": 1}
    found = restate_lib.build(old, "sheet-2")
    assert found["headline"] == {"rows": 4, "before": {"differ": 3, "share": "75.0%"},
                                 "after": {"differ": 2, "share": "50.0%"}}
    assert [c["host"] for c in found["changed"]] == ["drift.example"]
    assert found["moved"] == {"false->true": 1}
    assert found["summary"]["after"]["floating"] == {"above_listed": 1, "null": 3}
    assert "floating" not in found["summary"]["before"]


def test_a_restatement_is_signed_beside_the_sheet_and_verifies(site, capsys):
    path, signer, old = site
    sheet_bytes = (path / "sheets/x402-2026-11-16.json").read_bytes()
    entry = restate(str(path), "x402-2026-11-16", "sheet-2", signer, time="2026-11-17T07:00:00Z")
    assert entry["kind"] == "restatement" and entry["body"]["changed"] == 1
    assert (path / "sheets/x402-2026-11-16.json").read_bytes() == sheet_bytes      # the sheet is untouched
    report = verify(str(path))
    assert report.ok, report.checks
    assert any(c["check"].startswith("restatement of x402-2026-11-16") and c["ok"] for c in report.checks)
    page = (path / "index.html").read_text()
    assert "Restated." in page and "3 of 4 listings" in page and "restated under sheet-2" in page
    assert "Price is judged in dollars" in page
    with pytest.raises(RuntimeError, match="already restated"):
        restate(str(path), "x402-2026-11-16", "sheet-2", signer)


def test_a_tampered_restatement_is_caught(site):
    path, signer, _ = site
    entry = restate(str(path), "x402-2026-11-16", "sheet-2", signer)
    file = path / entry["body"]["file"]
    data = json.loads(file.read_text())
    data["headline"]["after"]["differ"] = 0
    file.write_bytes(restate_lib.to_bytes(data))
    report = verify(str(path))
    assert not report.ok
    bad = [c for c in report.checks if c["check"].startswith("restatement") and not c["ok"]]
    assert bad and "not the one the book signed" in bad[0]["detail"]


def test_no_restatement_is_written_without_its_reason():
    with pytest.raises(ValueError):
        restate_lib.build({"rule": "sheet-2", "rows": [], "id": "x"}, "sheet-1")


def test_the_next_sheet_under_sheet_2_logs_no_change_for_drift(site):
    path, signer, _ = site
    new = week("x402-2026-11-23", "2120", "sheet-2")      # the rate moved again; dollars as listed
    assert new["rule"] == "sheet-2" and "floating" in new["summary"]
    out = publish(str(path), new, signer, time="2026-11-23T07:00:00Z")
    log = json.loads((path / out["changes"]["body"]["file"]).read_text())
    assert log["rule"] == {"from": "sheet-1", "to": "sheet-2", "before_judged_again": True}
    assert not [c for c in log["changes"] if c["kind"] == "verdict_changed"]
    plain = changes_lib.diff(json.loads((path / "sheets/x402-2026-11-16.json").read_text()),
                             json.loads((path / "sheets/x402-2026-11-16.json").read_text()))
    assert "rule" not in plain                                    # one rule: the log is as it always was
    assert verify(str(path), every=True).ok
    page = (path / "index.html").read_text()
    assert "What changed since x402-2026-11-16:" in page and out["changes"]["body"]["file"] in page


def test_the_sheet_2_table_has_the_floating_column_and_reads_all_dollar_options(site):
    new = week("x402-2026-11-23", "2120", "sheet-2")
    lines = sheet_lib.to_csv(new).splitlines()
    head = lines[0].split(",")
    assert head[4:7] == ["price", "floating", "pay_to"]
    drift = next(line.split(",") for line in lines if "drift.example" in line)
    assert drift[4:7] == ["as_listed", "above_listed", "as_listed"]
    assert drift[head.index("listed_usd")] == "0.01" and drift[head.index("asked_usd")] == "0.01"
    old_head = sheet_lib.to_csv(site[2]).splitlines()[0].split(",")
    assert old_head == sheet_lib.CSV_COLUMNS                      # sheet-1 tables are rebuilt exactly as signed


def test_restate_from_the_command_line(site, capsys):
    path, signer, _ = site
    key = path.parent / "key.pem"
    key.write_text(signer.pem())
    assert main(["restate", str(path), "x402-2026-11-16", "--key-file", str(key)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["headline"]["after"]["differ"] == 2 and out["changed"] == 1
    assert len(entries_of("restatement", Book(str(path / "book.jsonl")).entries())) == 1


def test_a_run_confirms_a_dear_quote_with_the_sellers_example(tmp_path):
    """An endpoint priced by its input: its ceiling to an empty ask, its listed price to its own example."""
    ceiling, listed = "1000000000", "4990000"

    def priced_by_input(request):
        amount = listed if request.url.params.get("domain") else ceiling
        required = {"x402Version": 2, "accepts": [option(amount)],
                    "extensions": {"bazaar": {"info": {"input": {"type": "http", "method": "GET",
                                                                 "queryParams": {"domain": "a.com"}}}}}}
        header = base64.b64encode(json.dumps(required).encode()).decode()
        return httpx.Response(402, headers={"PAYMENT-REQUIRED": header}, json={})

    market = Market([item("https://names.example/price", listed)], {"names.example": priced_by_input})
    from agoranome_inspector.bazaar import select

    chosen = select(market.reader().read()["listings"], 3)
    seen = ask_all(chosen, market.fetcher(), Settings(host_pause=0, retry_pause=0, confirm_pause=0),
                   sleep=lambda s: None)
    row = seen["https://names.example/price"]
    assert "_example" not in row and row["again"]["request"] == "seller_example"
    built = sheet_lib.build("x402-2026-11-23", chosen, seen, index={"listings": 1, "complete": True}, probe={})
    verdict = built["rows"][0]["verdict"]
    assert (verdict["price"], verdict["matches_listing"]) == ("input_priced", None)
    assert "domain" not in json.dumps(built)                      # the example is sent, never published
    assert market.asked == ["GET names.example/price", "GET names.example/price"]


# --- The pick table of a restated sheet (A4 of the validation of 17 Nov 2026) ---------------------------------------
# Restating the 16 Nov sheet left its pick table on sheet-1's verdicts: 431 rows ranked last, 284 of them matching
# their listing under sheet-2. The pick ranks "asked what it lists" first and reads it from the verdicts, so the
# table is built again from the restated verdicts and signed beside the first one.

WORDS = ["search", "web"]


@pytest.fixture
def picked(tmp_path):
    from agoranome_inspector.publish import restate as restate_sheet

    signer = Signer.generate()
    old = week("x402-2026-11-16", "2105", "sheet-1")
    publish(str(tmp_path), old, signer, time="2026-11-16T07:00:00Z",
            words={r["resource"]: WORDS for r in old["rows"]})
    restate_sheet(str(tmp_path), "x402-2026-11-16", "sheet-2", signer, time="2026-11-17T07:00:00Z")
    return tmp_path, signer, old


def _honest(table):
    return {r["host"]: r["honest"] for r in table["rows"]}


def test_the_pick_table_is_built_again_from_the_restated_verdicts_beside_the_first(picked):
    from agoranome_inspector import pick as pick_lib
    from agoranome_inspector.picking import load_tables
    from agoranome_inspector.publish import restate_pick

    path, signer, _ = picked
    first = (path / "picks/x402-2026-11-16.json").read_bytes()
    entry = restate_pick(str(path), "x402-2026-11-16", "sheet-2", signer, time="2026-11-17T08:00:00Z")
    assert entry["kind"] == "pick" and entry["body"]["file"] == "picks/x402-2026-11-16.sheet-2.json"
    assert entry["body"]["restatement"]["rule"] == "sheet-2"
    assert entry["body"]["restatement"]["replaces"] == "picks/x402-2026-11-16.json"
    assert (path / "picks/x402-2026-11-16.json").read_bytes() == first          # the first table is untouched
    before = json.loads(first)
    after = json.loads((path / entry["body"]["file"]).read_text())
    assert _honest(before) == {"drift.example": 2, "dear.example": 2, "swap.example": 2, "honest.example": 0}
    assert _honest(after) == {"drift.example": 0, "dear.example": 2, "swap.example": 2, "honest.example": 0}
    assert after["rule"] == "pick-1" and after["restated"] == {"rule": "sheet-2",
                                                               "file": "restatements/x402-2026-11-16.sheet-2.json"}
    assert [r["words"] for r in after["rows"]] == [WORDS] * 4                   # the words the run had that day
    # Every reader ranks by the newest pick entry: the drift seller now ranks with the honest one.
    tables = load_tables(str(path))
    assert [t["entry"]["seq"] for t in tables] == [entry["seq"]]
    found = pick_lib.rank(tables, "web search")
    assert {p["host"] for p in found["picked"][:2]} == {"drift.example", "honest.example"}
    # The verifier recomputes it from the sheet judged again, and the first table still verifies too.
    newest = verify(str(path))
    assert newest.ok, newest.checks
    assert any(c["check"] == "pick picks/x402-2026-11-16.sheet-2.json" and c["ok"]
               and "judged again under sheet-2" in c["detail"] for c in newest.checks)
    every = verify(str(path), every=True)
    assert every.ok and any(c["check"] == "pick picks/x402-2026-11-16.json" and c["ok"] for c in every.checks)
    page = (path / "index.html").read_text()
    assert "its verdicts restated under <code>sheet-2</code>" in page
    # Once only.
    assert restate_pick(str(path), "x402-2026-11-16", "sheet-2", signer) is None


def test_a_restated_table_that_does_not_follow_from_the_restatement_is_caught(picked):
    from agoranome_inspector import pick as pick_lib
    from agoranome_inspector.canonical import canonical
    from agoranome_inspector.publish import BOOK, _write

    path, signer, old = picked
    book = Book(str(path / BOOK))
    entries = book.entries()
    restatement = entries_of("restatement", entries)[-1]
    sheet_entry = entries_of("sheet", entries)[-1]
    # Marked as restated, but built from the sheet-1 verdicts: the drift seller still ranked last.
    forged = pick_lib.table(old, {r["resource"]: WORDS for r in old["rows"]},
                            {"rule": "sheet-2", "file": restatement["body"]["file"]})
    file = "picks/x402-2026-11-16.sheet-2.json"
    sha = _write(path / file, canonical(forged) + b"\n")
    body = {"rule": "pick-1", "market": "x402", "sheet": {"seq": sheet_entry["seq"], "id": "x402-2026-11-16"},
            "file": file, "sha256": sha, "rows": len(forged["rows"]), "left_out": forged["left_out"],
            "restatement": {"seq": restatement["seq"], "rule": "sheet-2", "replaces": "picks/x402-2026-11-16.json"}}
    book.append(signer, "pick", body)
    bad = [c for c in verify(str(path)).checks if not c["ok"]]
    assert bad and "does not follow from its sheet" in bad[0]["detail"]
    # And one naming a restatement the book lacks.
    book.append(signer, "pick", {**body, "restatement": {**body["restatement"], "seq": sheet_entry["seq"]}})
    bad = [c for c in verify(str(path)).checks if not c["ok"]]
    assert bad and "names a restatement of its sheet that the book lacks" in bad[-1]["detail"]


def test_only_the_markets_newest_sheet_gets_a_restated_pick_table(tmp_path):
    from agoranome_inspector.publish import restate as restate_sheet
    from agoranome_inspector.publish import restate_pick

    signer = Signer.generate()
    old = week("x402-2026-11-16", "2105", "sheet-1")
    publish(str(tmp_path), old, signer, words={r["resource"]: WORDS for r in old["rows"]})
    new = week("x402-2026-11-23", "2120", "sheet-2")
    publish(str(tmp_path), new, signer, words={r["resource"]: WORDS for r in new["rows"]})
    restate_sheet(str(tmp_path), "x402-2026-11-16", "sheet-2", signer)
    # A restated table for 16 Nov would become the newest pick entry and replace 23 Nov's in every reader.
    assert restate_pick(str(tmp_path), "x402-2026-11-16", "sheet-2", signer) is None
    picks = entries_of("pick", Book(str(tmp_path / "book.jsonl")).entries())
    assert [p["body"]["sheet"]["id"] for p in picks] == ["x402-2026-11-16", "x402-2026-11-23"]
    with pytest.raises(RuntimeError, match="not restated"):
        restate_pick(str(tmp_path), "x402-2026-11-23", "sheet-2", signer)


def test_the_restate_command_restates_the_pick_of_a_sheet_restated_already_and_best_buy_follows(picked, capsys):
    path, signer, _ = picked
    key = path.parent / "key.pem"
    key.write_text(signer.pem())
    # The 16 Nov sheet was restated before pick tables were: the command goes on to the pick table.
    assert main(["restate", str(path), "x402-2026-11-16", "--rule", "sheet-2", "--key-file", str(key)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["already"] is True and out["pick"]["file"] == "picks/x402-2026-11-16.sheet-2.json"
    assert out["pick"]["rows"] == 4
    entries = Book(str(path / "book.jsonl")).entries()
    assert len(entries_of("restatement", entries)) == 1 and len(entries_of("pick", entries)) == 2
    assert main(["restate", str(path), "x402-2026-11-16", "--rule", "sheet-2", "--key-file", str(key)]) == 0
    assert json.loads(capsys.readouterr().out)["pick"] is None                   # nothing twice
    # The best-buy file is built from the newest pick table: the restated one.
    assert main(["best-buy", str(path), "--key-file", str(key)]) == 0
    capsys.readouterr()
    buys = entries_of("bestbuy", Book(str(path / "book.jsonl")).entries())
    restated_pick = entries_of("pick", Book(str(path / "book.jsonl")).entries())[-1]
    assert [p["seq"] for p in buys[-1]["body"]["sources"]["picks"]] == [restated_pick["seq"]]
    found = json.loads((path / buys[-1]["body"]["file"]).read_text())
    rows = {r["host"]: r["honest"] for c in found["categories"] for r in c["rows"]}
    assert rows["drift.example"] == 0
    assert verify(str(path), every=True).ok
