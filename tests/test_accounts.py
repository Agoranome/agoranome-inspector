"""Small sums carry within a quarter (carry-1); payouts, licences, grants and credits in the accounts (accounts-1);
each month closed with every source (close-1)."""

import hashlib
import json

import pytest

from agoranome_inspector import accounts, pledge
from agoranome_inspector.cli import main

from fakes import standard_market

CAUSE = "0x" + "c0" * 20
TX = "0x" + "ab" * 32
DOC = hashlib.sha256(b"the payout statement").hexdigest()


def month(period, counted, given=0, standing=None):
    owes = pledge.owed(counted, 1500)
    transfers = [{"tx_hash": "0x" + f"{int(period[5:]):02d}" * 32, "amount_atomic": str(given), "recipient": CAUSE,
                  "verified": True}] if given else []
    out = {"period": period, "counted_atomic": str(counted), "owed_atomic": str(owes), "given_atomic": str(given),
           "transfers": transfers, "status": "kept" if given >= owes else "outstanding"}
    if standing:
        out["standing"] = standing
    return out


def test_a_month_owing_under_a_dollar_carries_and_the_quarter_end_settles_it():
    # 15% of $2 is $0.30 (carried), of $4 another $0.60 (now $0.90, still carried), of $1 in March $0.15: the
    # quarter ends, so $1.05 is owed and the transfer settles all three.
    months = [month("2027-01", 2_000_000), month("2027-02", 4_000_000), month("2027-03", 1_000_000, 1_050_000)]
    rows = pledge.standing(months)
    assert [r["standing"] for r in rows] == ["carried", "carried", "kept"]
    assert [r["balance_atomic"] for r in rows] == ["300000", "900000", "0"]
    # $1 or more is owed at once, inside the quarter too.
    rows = pledge.standing([month("2027-01", 10_000_000)])
    assert rows[0]["standing"] == "owed" and rows[0]["balance_atomic"] == "1500000"
    # A quarter's end owes whatever is left, however small.
    assert pledge.standing([month("2027-03", 1_000_000)])[0]["standing"] == "owed"


def test_late_only_once_a_cause_is_named_and_past_the_grace():
    months = [month("2027-01", 2_000_000), month("2027-02", 10_000_000)]
    body = {"recipient": CAUSE, "months": months}
    # February owes $1.80 (with January's $0.30): due, late 45 days after February ends.
    assert pledge.late(body, "2027-04-10") == []
    assert len(pledge.late(body, "2027-04-15")) == 1
    # A carried balance whose quarter ended with nothing after it in the book.
    small = {"recipient": CAUSE, "months": [month("2027-01", 2_000_000)]}
    assert pledge.late(small, "2027-05-14") == [] and len(pledge.late(small, "2027-05-16")) == 1
    # No cause named: what is owed is kept and shown, never late.
    assert pledge.late({"recipient": None, "months": months}, "2028-01-01") == []


def test_the_labs_own_standing_must_match_carry_1():
    body = {"pledge_bps": 1500, "months": [month("2027-01", 2_000_000, standing="carried")]}
    body["totals"] = {k: body["months"][0][f"{k}_atomic"] if k != "revenue" else "0" for k in
                      ("revenue", "counted", "owed", "given")}
    body["months"][0]["revenue_atomic"] = "0"
    assert pledge.check(body) == []
    body["months"][0]["standing"] = "owed"
    assert any("carry-1 gives carried" in p for p in pledge.check(body))


def statement(**over):
    args = dict(kind="payout", payer="The merchant", period="2026-12", amount_usd="46.05", document_sha256=DOC)
    args.update(over)
    return accounts.statement_body(**args)


def test_each_type_owes_the_pledge_by_accounts_1():
    assert statement()["earned"] and statement()["pledged"]
    licence = statement(kind="licence", payer="A platform", amount_usd="473.55", list_price_usd="499")
    assert licence["pledged"] and licence["list_price_usd"] == "499"
    prize = statement(kind="prize", payer="A fund", amount_usd="1000", grant_tests=True)
    assert prize["earned"] and prize["pledged"] and prize["grant_tests"] == "passed"
    work = statement(kind="grant", payer="NLnet", amount_usd="5400", currency="EUR", amount="5000", grant_tests=True)
    assert not work["earned"] and not work["pledged"] and work["paid"] == {"currency": "EUR", "amount": "5000"}
    agreed = statement(kind="grant", payer="NLnet", amount_usd="5400", grant_tests=True, funder_agrees_sha256=DOC)
    assert agreed["pledged"] and not agreed["earned"]
    credit = statement(kind="credit", payer="Google Cloud", amount_usd="220")
    assert not credit["earned"] and not credit["pledged"]
    for body in (licence, prize, work, agreed, credit):
        assert accounts.check_statement(body) == []


@pytest.mark.parametrize("over, says", [
    (dict(kind="sponsor"), "type must be"),
    (dict(kind="grant", grant_tests=False), "five tests"),
    (dict(kind="licence"), "list price"),
    (dict(amount_usd="1.0000001"), "six decimals"),
    (dict(document_sha256="not a hash"), "SHA-256"),
    (dict(period="2026-13"), "YYYY-MM"),
    (dict(funder_agrees_sha256=DOC), "named work"),
    (dict(document_url="http://plain.example/doc"), "https"),
])
def test_money_that_breaks_a_rule_is_refused(over, says):
    with pytest.raises(ValueError, match=says):
        statement(**over)


def test_a_statement_whose_flags_were_changed_is_found():
    body = statement(kind="credit", payer="Google Cloud", amount_usd="220")
    body["pledged"] = True
    assert accounts.check_statement(body)


def test_the_close_adds_every_source_and_the_standing_runs_on_its_total(tmp_path, monkeypatch, capsys):
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
    # The lab's ledger: $2 of x402 receipts in October, nothing given yet, no cause named.
    ledger = {"pledge_bps": 1500, "terms": {"recipient": None}, "months": [],
              "periods": [{"period": "2026-10", "receipts": 2, "revenue_atomic": "2000000",
                           "counted_atomic": "2000000", "owed_atomic": "300000", "given_atomic": "0",
                           "status": "outstanding", "standing": "carried", "merkle_root": "0x" + "1" * 64,
                           "donations": []}]}
    monkeypatch.setattr(anchor, "read_ledger", lambda url: json.dumps(ledger).encode())
    assert main(["anchor-lab", str(site), "--key-file", str(key)]) == 0
    doc = tmp_path / "licence.pdf"
    doc.write_bytes(b"the licence, signed")
    assert main(["statement", str(site), "--type", "licence", "--from", "A platform", "--period", "2026-10",
                 "--amount-usd", "473.55", "--list-price-usd", "499", "--document", str(doc),
                 "--key-file", str(key)]) == 0
    assert main(["statement", str(site), "--type", "credit", "--from", "Google Cloud", "--period", "2026-10",
                 "--amount-usd", "220", "--document-sha256", DOC, "--key-file", str(key)]) == 0
    capsys.readouterr()
    assert main(["close", str(site), "--key-file", str(key)]) == 0
    closed = json.loads(capsys.readouterr().out)["closed"]
    # x402: $0.30; the licence: 15% of $473.55 = $71.0325; the credit: nothing.
    assert closed == [{"seq": closed[0]["seq"], "period": "2026-10", "owed_atomic": str(300_000 + 71_032_500)}]
    assert main(["close", str(site), "--key-file", str(key)]) == 0
    assert json.loads(capsys.readouterr().out) == {"unchanged": True}
    published = json.loads((site / "accounts.json").read_text())
    assert published["licensees"] == ["A platform"] and published["closes"][0]["earned_atomic"] == "475550000"
    assert published["closes"][0]["outside_atomic"] == "220000000"
    page = (site / "index.html").read_text()
    assert "The accounts" in page and "A platform" in page and "carry-1" in page
    assert main(["verify", str(site), f"--key={kid}", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    names = {c["check"]: c for c in out["checks"]}
    assert names["statements"]["ok"] and "1 credit, 1 licence" in names["statements"]["detail"]
    assert names["close 2026-10"]["ok"] and out["warnings"] == []
    # A close edited by hand no longer recomputes.
    entries = [json.loads(line) for line in (site / "book.jsonl").read_text().splitlines()]
    close = next(e for e in entries if e["kind"] == "close")
    close["body"]["owed_atomic"] = "1"
    assert accounts.check_close(close, entries)
    close["body"]["owed_atomic"] = closed[0]["owed_atomic"]
    # The closed month owes every source: with the close, October is owed (over $1), not carried.
    owed = accounts.owed_by_period(entries)
    body = next(e for e in entries if e["kind"] == "pledge")["body"]
    assert pledge.standing(body["months"], owed_by_period=owed)[0]["standing"] == "owed"
    assert pledge.standing(body["months"])[0]["standing"] == "carried"

    # The plan's gates: the lab sees only its own receipts ($2, under the bar), the accounts add the licence.
    from agoranome_inspector import gates

    lab = {"kind": "agoranome.gates", "format": 1, "as_of": "2026-11-20", "go_ahead": "2026-11-11", "day": 9,
           "gates": [{"id": "outside_use", "status": "waiting", "by": None, "signs": {"citations": []}},
                     {"id": "data_goods", "status": "open", "by": "2027-01-10"},
                     {"id": "earned", "status": "open", "by": "2027-02-09", "earned_30d_usd": "$2.00"},
                     {"id": "ask_test", "status": "not_run"}]}
    monkeypatch.setattr(gates, "read_gates", lambda url: json.dumps(lab).encode())
    capsys.readouterr()
    assert main(["gates", str(site), "--key-file", str(key)]) == 0
    said = json.loads(capsys.readouterr().out)
    assert said["money"] == "met" and said["gates"]["earned"] == "open"
    assert main(["gates", str(site), "--key-file", str(key)]) == 0
    assert json.loads(capsys.readouterr().out) == {"unchanged": True, "money": "met"}
    shown = json.loads((site / "gates.json").read_text())
    assert shown["earned_month"] == {"period": "2026-10", "close_seq": closed[0]["seq"], "earned_atomic": "475550000",
                                     "bar_atomic": "47060000", "covers": True}
    assert "citations" not in json.dumps(shown) and "Gates" in (site / "index.html").read_text()
    assert main(["verify", str(site), f"--key={kid}", "--json"]) == 0
    checks = {c["check"]: c for c in json.loads(capsys.readouterr().out)["checks"]}
    assert any(name.startswith("gates ") and c["ok"] for name, c in checks.items())
    entries = [json.loads(line) for line in (site / "book.jsonl").read_text().splitlines()]
    reading = next(e for e in entries if e["kind"] == "gates")
    assert gates.check({**reading, "body": {**reading["body"], "money": "open"}}, entries)
    with pytest.raises(ValueError):
        gates.lab_gates(json.dumps({**lab, "gates": lab["gates"][:3]}).encode())
    with pytest.raises(ValueError):
        gates.lab_gates(json.dumps({**lab, "gates": [{**g, "status": "great"} for g in lab["gates"]]}).encode())


def test_only_finished_months_with_income_are_closed():
    entries = [{"seq": 1, "kind": "pledge", "body": {"months": [{"period": "2026-10"}, {"period": "2026-11"}]}},
               {"seq": 2, "kind": "statement", "body": {"period": "2026-09"}},
               {"seq": 3, "kind": "close", "body": {"period": "2026-10"}}]
    assert accounts.months_to_close(entries, "2026-11-20T00:00:00Z") == ["2026-09"]
    assert accounts.months_to_close(entries, "2026-12-01T08:00:00Z") == ["2026-09", "2026-11"]
