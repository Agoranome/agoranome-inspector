"""From the index to a verified sheet: measure a fake market, publish, verify, then try to cheat."""

import json
from pathlib import Path

import pytest

from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.anchor import anchor_body, check_receipt
from agoranome_inspector.book import Book, entries_of
from agoranome_inspector.cli import main
from agoranome_inspector.keys import Signer
from agoranome_inspector.measure import Settings, run
from agoranome_inspector.merkle import merkle_proof, merkle_root, receipt_leaf
from agoranome_inspector.publish import publish
from agoranome_inspector.verify import proof_for, verify

from fakes import OTHER, honest, standard_market

def clock(value="2026-11-16T06:00:00Z"):
    return lambda: value


def measure(market, run_id, publish_index_counts=False):
    found = run(run_id, reader=market.reader(), fetcher=market.fetcher(),
                settings=Settings(concurrency=4, host_pause=0, retry_pause=0, confirm_pause=0), clock=clock(f"{run_id}T06:00:00Z"))
    return sheet_lib.build(found["id"], found["listings"], found["seen"], index=found["index"],
                           probe=found["probe"], publish_index_counts=publish_index_counts)


@pytest.fixture
def site(tmp_path):
    signer = Signer.generate()
    market = standard_market()
    first = measure(market, "2026-11-16")
    publish(str(tmp_path), first, signer, time="2026-11-16T07:00:00Z")
    return tmp_path, signer, market, first


def rows(sheet):
    return {r["host"]: r for r in sheet["rows"]}


def test_the_sheet_judges_each_seller(site):
    _, _, market, sheet = site
    found = rows(sheet)
    assert "quiet.example" not in found                       # two payers: not real demand
    assert len(found) == 8
    assert found["honest.example"]["verdict"]["matches_listing"] is True
    assert found["honest.example"]["seen"]["fair_offer"] == "0.3"
    assert found["pricey.example"]["verdict"]["price"] == "above_listed"
    assert found["swap.example"]["verdict"]["pay_to"] == "different"
    assert found["legacy.example"]["verdict"]["price"] == "as_listed"   # v1 body, answered on POST
    assert found["legacy.example"]["seen"]["method"] == "POST"
    assert found["free.example"]["verdict"]["answer"] == "no_payment_asked"
    assert found["gone.example"]["verdict"]["answer"] == "gone"
    assert found["down.example"]["verdict"]["answer"] == "unreachable"
    assert found["down.example"]["seen"]["attempts"] == 2
    assert found["plain.example"]["verdict"]["answer"] == "declined"
    assert sheet["summary"]["matches_listing"] == {"false": 2, "null": 4, "true": 2}
    assert not any("plain.example" in a for a in market.asked)


def test_the_published_sheet_holds_no_index_counts(site):
    path, _, _, sheet = site
    text = (path / "sheets" / "2026-11-16.json").read_text()
    assert '"payers_30d"' not in text and '"calls_30d"' not in text
    assert sheet["selection"]["index_counts_published"] is False


def test_index_counts_only_when_asked():
    sheet = measure(standard_market(), "2026-11-16", publish_index_counts=True)
    assert rows(sheet)["honest.example"]["index"] == {"payers_30d": 5, "calls_30d": 20, "repeat_use": True}


def test_a_stranger_verifies_the_sheet_with_one_command(site, capsys):
    path, signer, _, _ = site
    assert main(["verify", str(path), f"--key={signer.kid}"]) == 0   # a kid may start with "-"
    out = capsys.readouterr().out
    assert out.strip().endswith("VERIFIED") and "FAIL" not in out


def test_the_change_log_is_published_and_verified(site):
    path, signer, market, _ = site
    market.sellers["honest.example"] = honest("4000", fair_offer="0.3")
    market.sellers["pricey.example"] = honest("5000")
    market.sellers["swap.example"] = honest("5000", OTHER.replace("2", "3"))
    market.sellers["gone.example"] = honest("1000")
    market.sellers["free.example"] = lambda request: (_ for _ in ()).throw(Exception("never"))
    market.items = [i for i in market.items if "down.example" not in i["resource"]]
    second = measure(market, "2026-11-23")
    out = publish(str(path), second, signer, time="2026-11-23T07:00:00Z")
    log = json.loads((path / out["changes"]["body"]["file"]).read_text())
    kinds = {(c["host"], c["kind"]) for c in log["changes"]}
    assert ("honest.example", "price_cut") in kinds
    assert ("pricey.example", "price_cut") in kinds
    assert ("pricey.example", "verdict_changed") in kinds
    assert ("swap.example", "pay_to_changed") in kinds
    assert ("gone.example", "came_back") in kinds
    assert ("down.example", "left") in kinds
    report = verify(str(path), every=True, pinned_kid=signer.kid)
    assert report.ok, report.lines()
    assert any(c["check"].startswith("changes 2026-11-16 to 2026-11-23") for c in report.checks)


def test_a_sheet_id_is_published_once(site):
    path, signer, _, sheet = site
    with pytest.raises(RuntimeError):
        publish(str(path), sheet, signer)


def _rewrite(path: Path, edit):
    data = json.loads(path.read_text())
    edit(data)
    path.write_bytes(sheet_lib.to_bytes(data))


def test_an_edited_row_is_caught(site):
    path, _, _, _ = site
    _rewrite(path / "sheets" / "2026-11-16.json",
             lambda s: s["rows"][0]["verdict"].update(matches_listing=True, price="as_listed"))
    report = verify(str(path))
    assert not report.ok
    assert any(c["check"].endswith("file") and not c["ok"] for c in report.checks)


def test_an_edited_row_with_a_matching_book_still_fails_the_signature(site):
    path, _, _, _ = site
    sheet_path = path / "sheets" / "2026-11-16.json"
    _rewrite(sheet_path, lambda s: s["rows"][0]["verdict"].update(matches_listing=True))
    book = path / "book.jsonl"
    lines = book.read_text().splitlines()
    entry = json.loads(lines[1])
    from agoranome_inspector.canonical import canonical, sha256_hex
    entry["body"]["sha256"] = sha256_hex(sheet_path.read_bytes())
    lines[1] = canonical(entry).decode()
    book.write_text("\n".join(lines) + "\n")
    report = verify(str(path))
    assert not report.ok and "hash does not match" in report.checks[0]["detail"]


def test_a_verdict_that_does_not_follow_from_its_row_is_caught(tmp_path):
    signer = Signer.generate()
    sheet = measure(standard_market(), "2026-11-16")
    target = rows(sheet)["pricey.example"]
    target["verdict"] = dict(target["verdict"], price="as_listed", matches_listing=True)
    sheet["summary"] = sheet_lib.summarize(sheet["rows"])
    publish(str(tmp_path), sheet, signer)     # signed, so only the rule can catch it
    report = verify(str(tmp_path))
    bad = [c for c in report.checks if not c["ok"]]
    assert [c["check"] for c in bad] == ["sheet 2026-11-16 verdicts"]
    assert "pricey.example" in bad[0]["detail"]


def test_a_tampered_table_is_caught(site):
    path, _, _, _ = site
    csv_path = path / "sheets" / "2026-11-16.csv"
    csv_path.write_text(csv_path.read_text().replace("above_listed", "as_listed"))
    report = verify(str(path))
    assert [c["check"] for c in report.checks if not c["ok"]] == ["sheet 2026-11-16 table"]


def test_a_seller_proves_its_row(site, capsys):
    path, _, _, _ = site
    found = proof_for(str(path), "https://honest.example/search")
    assert found["verified"] and found["row"]["host"] == "honest.example"
    assert main(["proof", str(path), "--resource", "https://swap.example/search"]) == 0
    with pytest.raises(LookupError):
        proof_for(str(path), "https://nobody.example/")


def test_a_book_naming_a_file_outside_the_site_is_refused(tmp_path):
    signer = Signer.generate()
    book = Book(str(tmp_path / "book.jsonl"))
    book.append(signer, "sheet", {"id": "x", "rule": "sheet-1", "file": "../../etc/passwd", "sha256": "0x00",
                                  "root": None, "rows": 0, "summary": {}})
    report = verify(str(tmp_path))
    assert not report.ok and "outside the site" in report.checks[-1]["detail"]


def test_the_lab_receipt_roots_join_the_book(site, capsys):
    path, signer, _, _ = site
    receipts = [{"receipt_id": f"r{i}", "payer": "0xabc", "amount_atomic": 1000 * (i + 1), "tx_hash": f"0x{i:064x}"}
                for i in range(5)]
    leaves = [receipt_leaf(r) for r in receipts]
    ledger = {"pledge": "15% of settled revenue", "terms": {"share": 0.15, "basis": "settled_revenue"},
              "months": [{"period": "2026-11", "merkle_root": merkle_root(leaves)}]}
    body = anchor_body("https://api.agoranome.com/impact/ledger", json.dumps(ledger).encode(), "2026-11-16T08:00:00Z")
    assert body["terms"]["share"] == "0.15"
    book = Book(str(path / "book.jsonl"))
    book.append(signer, "anchor", body)
    proof = {"period": "2026-11", "entry": receipts[2], "leaf": leaves[2], "proof": merkle_proof(leaves, leaves[2])}
    anchors = entries_of("anchor", book.entries())
    assert check_receipt(proof, anchors)["ok"]
    forged = dict(proof, entry=dict(receipts[2], amount_atomic=1))
    forged.pop("leaf")
    assert not check_receipt(forged, anchors)["ok"]
    assert not check_receipt(dict(proof, period="2026-10"), anchors)["ok"]
    proof_file = path.parent / "proof.json"
    proof_file.write_text(json.dumps(proof))
    assert main(["verify-receipt", str(path), str(proof_file)]) == 0
    report = verify(str(path))
    assert report.ok and any(c["check"] == "anchors" for c in report.checks)


def test_recheck_reports_agreement_without_failing(site):
    path, _, market, _ = site
    market.sellers["pricey.example"] = honest("5000")
    fetcher = market.fetcher()
    from agoranome_inspector.probe import probe
    report = verify(str(path), recheck_n=20,
                    ask=lambda row: probe(fetcher, row["resource"], retry_pause=0, sleep=lambda s: None))
    assert report.ok
    assert report.recheck["asked"] == 7 and "https://pricey.example/search" in report.recheck["differ"]


def test_a_difference_is_held_only_when_the_second_ask_gives_it_too(tmp_path):
    market = standard_market()
    answers = iter(["10000", "5000"])
    market.sellers["pricey.example"] = lambda request: honest(next(answers))(request)
    sheet = measure(market, "2026-11-16")
    found = rows(sheet)
    assert found["pricey.example"]["seen"]["again"] is not None
    assert (found["pricey.example"]["verdict"]["price"], found["pricey.example"]["verdict"]["matches_listing"]) == (
        "varies", None)
    assert found["swap.example"]["seen"]["again"] is not None
    assert found["swap.example"]["verdict"]["pay_to"] == "different"       # both asks named the other address
    assert "again" not in found["honest.example"]["seen"]                  # an offer that matches is asked once
    assert sheet["summary"]["confirmed"] == 2
    publish(str(tmp_path), sheet, Signer.generate())
    assert verify(str(tmp_path)).ok
