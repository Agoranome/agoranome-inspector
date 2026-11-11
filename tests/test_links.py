"""Operator links: facts beside the rows, rebuilt by the verifier from the sheets alone."""

import json

from agoranome_inspector import links as links_lib
from agoranome_inspector import mpp
from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.canonical import canonical, sha256_hex
from agoranome_inspector.keys import Signer
from agoranome_inspector.measure import Settings, run
from agoranome_inspector.publish import publish
from agoranome_inspector.verify import verify

from fakes import honest, standard_market
from fakes_mpp import OTHER, answer, by_path, challenge, standard_mpp_market

QUICK = Settings(concurrency=2, host_pause=0, retry_pause=0, confirm_pause=0)


def x402_sheet(market, sheet_id="x402-2026-11-16"):
    found = run(sheet_id, reader=market.reader(), fetcher=market.fetcher(), settings=QUICK,
                clock=lambda: "2026-11-16T06:00:00Z")
    return sheet_lib.build(found["id"], found["listings"], found["seen"], index=found["index"], probe=found["probe"])


def mpp_sheet(market, sheet_id="mpp-2026-11-16"):
    found = mpp.run(sheet_id, reader=market.catalog_reader(), fetcher=market.fetcher(), settings=QUICK,
                    clock=lambda: "2026-11-16T06:00:00Z")
    return mpp.build(found)


def test_hosts_paid_to_one_address_are_one_operator():
    found = links_lib.build([x402_sheet(standard_market())], "x")
    assert found["operators"] == [{"hosts": ["honest.example", "legacy.example", "pricey.example"], "evidence": [
        {"kind": "same_pay_to", "address": "0x1111111111111111111111111111111111111111", "hosts": {
            "honest.example": {"resources": ["x402 https://honest.example/search"], "count": 1},
            "legacy.example": {"resources": ["x402 https://legacy.example/search"], "count": 1},
            "pricey.example": {"resources": ["x402 https://pricey.example/search"], "count": 1}}}]}]
    assert found["platform_addresses"] == [] and found["same_host"] == []


def test_an_address_more_than_five_hosts_share_links_nobody_and_markets_join_by_host():
    x402 = standard_market()
    x402.sellers["fair.example"] = honest("5000", OTHER)
    x402.items.append(dict(x402.items[0], resource="https://fair.example/search"))
    mpp_market = standard_mpp_market()
    mpp_market.sellers["swap2.example"] = by_path({})
    found = links_lib.build([x402_sheet(x402), mpp_sheet(mpp_market)], "x")
    shared = {p["address"]: p["hosts"] for p in found["platform_addresses"]}
    assert shared == {"0x1111111111111111111111111111111111111111": 7}     # 3 x402 hosts and 4 MPP hosts
    assert [o["hosts"] for o in found["operators"]] == [["fair.example", "swap.example"]]
    assert [c["host"] for c in found["same_host"]] == ["fair.example"]
    assert set(found["same_host"][0]["markets"]) == {"mpp", "x402"}


def test_links_are_published_and_rebuilt_by_the_verifier(tmp_path):
    signer = Signer.generate()
    publish(str(tmp_path), x402_sheet(standard_market()), signer)
    market = standard_mpp_market()
    market.sellers["dear.example"] = by_path({"GET /v1/data": answer(challenge("30000", recipient=OTHER))})
    out = publish(str(tmp_path), mpp_sheet(market), signer)
    assert out["links"]["body"]["from"] == ["x402-2026-11-16", "mpp-2026-11-16"]
    report = verify(str(tmp_path), every=True)
    assert report.ok, report.lines()
    assert any(c["check"] == "links links/mpp-2026-11-16.json" and c["ok"] for c in report.checks)
    assert "Operators</h2>" in (tmp_path / "index.html").read_text()
    path = tmp_path / "links" / "mpp-2026-11-16.json"
    data = json.loads(path.read_text())
    data["operators"] = []
    path.write_bytes(canonical(data) + b"\n")
    assert not verify(str(tmp_path)).ok


def test_links_from_an_old_sheet_are_caught(tmp_path):
    from agoranome_inspector.book import Book

    signer = Signer.generate()
    market = standard_market()
    first = x402_sheet(market)
    publish(str(tmp_path), first, signer)
    publish(str(tmp_path), x402_sheet(market, "x402-2026-11-23"), signer)
    stale = links_lib.build([first], "stale")
    path = tmp_path / "links" / "stale.json"
    path.write_bytes(canonical(stale) + b"\n")
    Book(str(tmp_path / "book.jsonl")).append(signer, "links", {"from": stale["from"], "file": "links/stale.json",
                                                                 "sha256": sha256_hex(path.read_bytes()),
                                                                 "counts": stale["counts"]})
    bad = [c for c in verify(str(tmp_path)).checks if not c["ok"]]
    assert len(bad) == 1 and "not the newest sheet of each market" in bad[0]["detail"]
