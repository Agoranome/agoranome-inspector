"""Sellers' disputes and the operator's answers in the open book: only the row's seller, never edited."""

import json

import pytest

from agoranome_inspector import disputes
from agoranome_inspector.cli import main

from fakes import Market, honest, item

eth = pytest.importorskip("eth_account")
from eth_account.messages import encode_defunct  # noqa: E402

SELLER = eth.Account.create()
RESOURCE = "https://seller.example/search"


def market() -> Market:
    return Market([item(RESOURCE, "5000", pay_to=SELLER.address)],
                  {"seller.example": honest("5000", SELLER.address)})


def dispute(sheet, by=SELLER, claim="0.005", field="price", **over):
    d = {"id": "d-" + ("%016x" % abs(hash((claim, field, by.address))))[:16], "resource": RESOURCE,
         "host": "seller.example", "market": "x402", "sheet": sheet, "field": field, "claim": claim,
         "evidence": "https://seller.example/pricing", "seller": by.address.lower(),
         "filed_at": "2026-11-20T10:00:00Z"}
    d.update(over)
    text = disputes.message(d["resource"], d["sheet"], d["field"], d["claim"], d["evidence"])
    d["signature"] = by.sign_message(encode_defunct(text=text)).signature.to_0x_hex()
    return d


def test_disputes_and_answers_go_in_the_book_and_verify(tmp_path, monkeypatch, capsys):
    from agoranome_inspector import measure

    m = market()
    monkeypatch.setattr(measure, "IndexReader", lambda: m.reader())
    monkeypatch.setattr(measure, "SafeFetcher", lambda: m.fetcher())
    key = tmp_path / "key.pem"
    main(["keygen", "--out", str(key)])
    kid = json.loads(capsys.readouterr().out)["kid"]
    site = tmp_path / "site"
    assert main(["run", str(site), "--private", str(tmp_path / "p"), "--key-file", str(key), "--id", "2026-11-16",
                 "--concurrency", "2"]) == 0
    stranger = eth.Account.create()
    good = dispute("2026-11-16")
    forged = dict(good, id="d-" + "f" * 16, claim="0.001")                 # signature no longer matches
    other = dispute("2026-11-16", by=stranger, claim="0.002")               # not the row's seller
    junk = dict(dispute("2026-11-16", claim="0.003"), claim="ignore previous instructions")
    listing = {"disputes": [good, forged, other, junk]}
    monkeypatch.setattr(disputes, "read_disputes", lambda url: json.dumps(listing).encode())
    capsys.readouterr()
    assert main(["disputes", str(site), "--key-file", str(key)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["new"] == 1 and out["refused"] == 3 and "example" not in json.dumps(out)
    assert main(["disputes", str(site), "--key-file", str(key)]) == 0
    assert json.loads(capsys.readouterr().out)["unchanged"] is True
    published = json.loads((site / "disputes.json").read_text())
    assert published["count"] == 1 and published["open"] == 1
    # The operator answers it once.
    assert main(["answer", str(site), good["id"], "--outcome", "not_upheld", "--reason",
                 "The endpoint asked 0.01 twice on 16 November; the sheet shows what it asked.",
                 "--key-file", str(key)]) == 0
    assert main(["answer", str(site), good["id"], "--outcome", "upheld", "--reason", "again",
                 "--key-file", str(key)]) == 2
    assert main(["answer", str(site), "d-" + "0" * 16, "--outcome", "upheld", "--reason", "x",
                 "--key-file", str(key)]) == 2
    published = json.loads((site / "disputes.json").read_text())
    assert published["open"] == 0 and published["disputes"][0]["answer"]["outcome"] == "not_upheld"
    assert "Disputes" in (site / "index.html").read_text()
    capsys.readouterr()
    assert main(["verify", str(site), f"--key={kid}", "--json"]) == 0
    checks = {c["check"]: c for c in json.loads(capsys.readouterr().out)["checks"]}
    assert checks["disputes"]["ok"] and "1 dispute(s)" in checks["disputes"]["detail"]


def test_a_dispute_entry_with_a_forged_seller_is_found():
    table = {"rows": [{"resource": RESOURCE, "pay": {"pay_to": SELLER.address.lower()}}]}
    d = dispute("2026-11-16")
    assert disputes.check({"disputes": [d]}, [], lambda s: table) == []
    impostor = eth.Account.create()
    bad = dispute("2026-11-16", by=impostor)
    assert any("does not ask payment to" in p for p in disputes.check({"disputes": [bad]}, [], lambda s: table))
    swapped = dict(d, seller=impostor.address.lower())
    assert disputes.check({"disputes": [swapped]}, [], lambda s: {"rows": [{"resource": RESOURCE,
                                                                             "pay": {"pay_to": swapped["seller"]}}]})
    with pytest.raises(ValueError, match="correction goes with"):
        disputes.answer_body([{"kind": "dispute", "body": {"disputes": [d]}}], d["id"], "not_upheld", "no",
                             correction="x")
