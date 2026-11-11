"""The 15% pledge in the open book: the lab's figures copied as read, their arithmetic, and the transfers on Base."""

import json

from agoranome_inspector import pledge
from agoranome_inspector.cli import main
from agoranome_inspector.merkle import merkle_root, receipt_leaf

from fakes import standard_market

CAUSE = "0x" + "c0" * 20
TX = "0x" + "ab" * 32


def ledger(counted=2_000_000, owed=None, given=300_000, status=None, transfers=None, recipient=CAUSE):
    """The lab's /impact/ledger with figures published: one month, $2 earned that owes the pledge."""
    owed = pledge.owed(counted, 1500) if owed is None else owed
    receipts = [{"receipt_id": "r1", "payer": "0xabc", "amount_atomic": counted, "tx_hash": "0x01"}]
    transfers = [{"tx_hash": TX, "amount_atomic": str(given), "recipient": recipient, "verified": True}] \
        if transfers is None else transfers
    return {
        "pledge": "15% of settled revenue", "pledge_bps": 1500,
        "terms": {"share": 0.15, "basis": "settled", "recipient": recipient},
        "totals": {}, "months": [{"period": "2026-11", "merkle_root": merkle_root([receipt_leaf(receipts[0])])}],
        "periods": [{"period": "2026-11", "receipts": 1, "revenue_atomic": str(counted),
                     "counted_atomic": str(counted), "owed_atomic": str(owed), "given_atomic": str(given),
                     "status": status or ("kept" if given >= owed else "outstanding"),
                     "merkle_root": merkle_root([receipt_leaf(receipts[0])]), "donations": transfers}],
    }


def body_of(data, read_at="2026-12-01T08:00:00Z"):
    return pledge.pledge_body("https://api.agoranome.com/impact/ledger", json.dumps(data).encode(), read_at)


def test_the_figures_are_copied_in_strict_formats_and_add_up():
    body = body_of(ledger())
    assert body["pledge_bps"] == 1500 and body["recipient"] == CAUSE
    month = body["months"][0]
    assert (month["counted_atomic"], month["owed_atomic"], month["given_atomic"]) == ("2000000", "300000", "300000")
    assert month["status"] == "kept" and month["transfers"][0]["tx_hash"] == TX
    assert body["totals"]["owed"] == "300000" and body["outstanding_atomic"] == "0"
    assert pledge.check(body) == []
    # Owed rounds up to the next unit, the lab's rule: 15% of 7 units is 2.
    assert pledge.owed(7, 1500) == 2


def test_figures_that_do_not_follow_the_rule_are_found():
    assert any("owes 300000" in p for p in pledge.check(body_of(ledger(owed=200_000))))
    assert any("status kept" in p for p in pledge.check(body_of(ledger(given=100_000, status="kept"))))
    unverified = [{"tx_hash": TX, "amount_atomic": "300000", "recipient": CAUSE, "verified": False}]
    assert any("add up to 0" in p for p in pledge.check(body_of(ledger(transfers=unverified))))


def test_a_ledger_without_figures_gives_no_pledge_entry_and_junk_is_dropped():
    withheld = {"pledge": "15% of settled revenue", "months": [{"period": "2026-11", "merkle_root": "0x" + "1" * 64}]}
    assert body_of(withheld) is None
    data = ledger(transfers=[{"tx_hash": "pay me now", "amount_atomic": "1"},
                             {"tx_hash": TX, "amount_atomic": "300000", "recipient": "an instruction",
                              "verified": True}])
    month = body_of(data)["months"][0]
    assert len(month["transfers"]) == 1 and month["transfers"][0]["recipient"] is None


def test_the_weekly_reading_puts_the_pledge_in_the_book_once_and_the_verifier_checks_it(tmp_path, monkeypatch,
                                                                                         capsys):
    from agoranome_inspector import anchor, measure

    market = standard_market()
    monkeypatch.setattr(measure, "IndexReader", lambda: market.reader())
    monkeypatch.setattr(measure, "SafeFetcher", lambda: market.fetcher())
    key = tmp_path / "key.pem"
    main(["keygen", "--out", str(key)])
    kid = json.loads(capsys.readouterr().out)["kid"]
    site = tmp_path / "site"
    assert main(["run", str(site), "--private", str(tmp_path / "p"), "--key-file", str(key), "--id", "2026-11-16",
                 "--concurrency", "2"]) == 0
    reading = {"data": ledger()}
    monkeypatch.setattr(anchor, "read_ledger", lambda url: json.dumps(reading["data"]).encode())
    assert main(["anchor-lab", str(site), "--key-file", str(key)]) == 0
    assert main(["anchor-lab", str(site), "--key-file", str(key)]) == 0     # the same figures: no second entry
    kinds = [json.loads(line)["kind"] for line in (site / "book.jsonl").read_text().splitlines()]
    assert kinds.count("pledge") == 1 and kinds.count("anchor") == 2
    published = json.loads((site / "pledge.json").read_text())
    assert published["totals"]["given"] == "300000" and published["book_entry"]["seq"] == kinds.index("pledge")
    assert "15% pledge" in (site / "index.html").read_text()
    capsys.readouterr()
    assert main(["verify", str(site), f"--key={kid}", "--json"]) == 0
    checks = {c["check"]: c for c in json.loads(capsys.readouterr().out)["checks"]}
    pledge_check = next(c for name, c in checks.items() if name.startswith("pledge"))
    assert pledge_check["ok"] and "$0.30 owed at 15%" in pledge_check["detail"]
    # Figures that don't add up are refused, not signed.
    reading["data"] = ledger(owed=1)
    assert main(["anchor-lab", str(site), "--key-file", str(key)]) == 3
    kinds = [json.loads(line)["kind"] for line in (site / "book.jsonl").read_text().splitlines()]
    assert kinds.count("pledge") == 1


def transfer_receipt(to=CAUSE, value=300_000, status="0x1", token=pledge.BASE_USDC):
    return {"status": status, "logs": [{
        "address": token, "data": hex(value),
        "topics": [pledge.TRANSFER_TOPIC, "0x" + "0" * 24 + "11" * 20, "0x" + "0" * 24 + to[2:]]}]}


def rpc(answer):
    def post(url, data):
        asked = json.loads(data)
        assert asked["method"] == "eth_getTransactionReceipt" and asked["params"] == [TX]
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": answer}).encode()
    return post


def test_each_transfer_is_checked_on_the_chain_with_an_rpc():
    body = body_of(ledger())
    assert pledge.check_transfers(body, "https://rpc.test", rpc(transfer_receipt())) == []
    assert "under the 300000" in pledge.check_transfers(body, "https://rpc.test", rpc(transfer_receipt(value=1)))[0]
    elsewhere = transfer_receipt(to="0x" + "dd" * 20)
    assert "0 USDC units reached" in pledge.check_transfers(body, "https://rpc.test", rpc(elsewhere))[0]
    other_token = transfer_receipt(token="0x" + "ee" * 20)
    assert pledge.check_transfers(body, "https://rpc.test", rpc(other_token))
    assert "no successful" in pledge.check_transfers(body, "https://rpc.test", rpc(transfer_receipt(status="0x0")))[0]
    assert "no successful" in pledge.check_transfers(body, "https://rpc.test", rpc(None))[0]
