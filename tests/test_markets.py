"""One book, several markets: each market's sheets chain their own change logs, and the verifier checks the
newest sheet of each market."""

import json

from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.book import Book
from agoranome_inspector.canonical import canonical, sha256_hex
from agoranome_inspector.keys import Signer
from agoranome_inspector.measure import Settings, run
from agoranome_inspector.publish import publish
from agoranome_inspector.verify import proof_for, verify

from fakes import honest, standard_market


def measure(market, sheet_id, name="x402"):
    found = run(sheet_id, reader=market.reader(), fetcher=market.fetcher(),
                settings=Settings(concurrency=4, host_pause=0, retry_pause=0, confirm_pause=0),
                clock=lambda: "2026-11-16T06:00:00Z")
    return sheet_lib.build(found["id"], found["listings"], found["seen"], index=found["index"],
                           probe=found["probe"], market=name)


def test_the_default_id_names_the_market():
    market = standard_market()
    found = run(reader=market.reader(), fetcher=market.fetcher(),
                settings=Settings(concurrency=4, host_pause=0, retry_pause=0, confirm_pause=0),
                clock=lambda: "2026-11-16T06:00:00Z")
    assert found["id"] == "x402-2026-11-16"


def test_change_logs_stay_within_their_market(tmp_path):
    signer = Signer.generate()
    x402, other = standard_market(), standard_market()
    publish(str(tmp_path), measure(x402, "x402-2026-11-16"), signer)
    publish(str(tmp_path), measure(other, "mpp-2026-11-16", name="mpp"), signer)
    x402.sellers["pricey.example"] = honest("5000")
    out = publish(str(tmp_path), measure(x402, "x402-2026-11-23"), signer)
    assert out["changes"]["body"]["from"] == "x402-2026-11-16"
    assert out["changes"]["body"]["market"] == "x402"
    assert out["sheet"]["body"]["market"] == "x402"
    report = verify(str(tmp_path))
    assert report.ok, report.lines()
    checked = [c["check"] for c in report.checks if c["check"].endswith(" rule")]
    assert checked == ["sheet mpp-2026-11-16 rule", "sheet x402-2026-11-23 rule"]     # the newest of each
    assert verify(str(tmp_path), every=True).ok
    page = (tmp_path / "index.html").read_text()
    assert "x402: sheet x402-2026-11-23" in page and "MPP: sheet mpp-2026-11-16" in page
    assert proof_for(str(tmp_path), "https://pricey.example/search")["sheet"] == "x402-2026-11-23"


def test_a_change_log_that_skips_a_sheet_is_caught(tmp_path):
    signer = Signer.generate()
    market = standard_market()
    first = measure(market, "x402-2026-11-16")
    publish(str(tmp_path), first, signer)
    publish(str(tmp_path), measure(market, "x402-2026-11-23"), signer)
    third = measure(market, "x402-2026-11-30")
    sheet_file = tmp_path / "sheets" / "x402-2026-11-30.json"
    sheet_file.write_bytes(sheet_lib.to_bytes(third))
    csv_file = tmp_path / "sheets" / "x402-2026-11-30.csv"
    csv_file.write_text(sheet_lib.to_csv(third))
    book = Book(str(tmp_path / "book.jsonl"))
    book.append(signer, "sheet", {"id": third["id"], "market": "x402", "rule": third["rule"],
                                  "file": "sheets/x402-2026-11-30.json", "sha256": sha256_hex(sheet_file.read_bytes()),
                                  "root": sheet_lib.root(third), "rows": len(third["rows"]),
                                  "summary": third["summary"],
                                  "csv": {"file": "sheets/x402-2026-11-30.csv",
                                          "sha256": sha256_hex(csv_file.read_bytes())}})
    from agoranome_inspector import changes
    log = changes.diff(first, third)        # against the sheet two back, not the one just before
    log_file = tmp_path / "changes" / "x402-2026-11-30.json"
    log_file.write_bytes(canonical(log) + b"\n")
    book.append(signer, "changes", {"market": "x402", "from": log["from"], "to": log["to"],
                                    "file": "changes/x402-2026-11-30.json",
                                    "sha256": sha256_hex(log_file.read_bytes()), "counts": log["counts"]})
    report = verify(str(tmp_path))
    bad = [c for c in report.checks if not c["ok"]]
    assert len(bad) == 1 and "not the x402 sheet just before" in bad[0]["detail"]


def test_a_sheet_filed_under_another_market_is_caught(tmp_path):
    signer = Signer.generate()
    sheet = measure(standard_market(), "x402-2026-11-16", name="mpp")
    path = tmp_path / "sheets" / "x402-2026-11-16.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(sheet_lib.to_bytes(sheet))
    book = Book(str(tmp_path / "book.jsonl"))
    book.open(signer)
    book.append(signer, "sheet", {"id": sheet["id"], "market": "x402", "rule": sheet["rule"],
                                  "file": "sheets/x402-2026-11-16.json", "sha256": sha256_hex(path.read_bytes()),
                                  "root": sheet_lib.root(sheet), "rows": len(sheet["rows"]),
                                  "summary": sheet["summary"]})
    report = verify(str(tmp_path))
    assert [c["check"] for c in report.checks if not c["ok"]] == ["sheet x402-2026-11-16 rule"]
    assert json.loads(path.read_text())["market"] == "mpp"
