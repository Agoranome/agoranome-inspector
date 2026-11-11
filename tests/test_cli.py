"""The operator's commands, end to end, against the fake market."""

import json

from agoranome_inspector import measure
from agoranome_inspector.cli import main
from agoranome_inspector.merkle import merkle_root, receipt_leaf

from fakes import standard_market


def test_keygen_run_note_anchor_and_verify(tmp_path, monkeypatch, capsys):
    market = standard_market()
    monkeypatch.setattr(measure, "IndexReader", lambda: market.reader())
    monkeypatch.setattr(measure, "SafeFetcher", lambda: market.fetcher())
    key = tmp_path / "key.pem"
    assert main(["keygen", "--out", str(key)]) == 0
    kid = json.loads(capsys.readouterr().out)["kid"]
    assert oct(key.stat().st_mode)[-3:] == "600"
    assert main(["keygen", "--out", str(key)]) == 1            # never overwrites a key
    site, private = tmp_path / "site", tmp_path / "private"
    assert main(["run", str(site), "--private", str(private), "--key-file", str(key), "--id", "2026-11-16",
                 "--concurrency", "2"]) == 0
    assert (private / "run-2026-11-16.json").exists()
    assert '"payers_30d"' in (private / "run-2026-11-16.json").read_text()
    assert main(["note", str(site), "Method note: nothing changed.", "--key-file", str(key)]) == 0
    receipts = [{"receipt_id": "r1", "payer": "0xabc", "amount_atomic": 1000, "tx_hash": "0x01"}]
    ledger = {"months": [{"period": "2026-11", "merkle_root": merkle_root([receipt_leaf(receipts[0])])}]}
    import agoranome_inspector.anchor as anchor
    monkeypatch.setattr(anchor, "read_ledger", lambda url: json.dumps(ledger).encode())
    assert main(["anchor-lab", str(site), "--key-file", str(key)]) == 0
    capsys.readouterr()
    assert main(["verify", str(site), f"--key={kid}", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] and any(c["check"] == "anchors" for c in report["checks"])
    assert main(["verify", str(site), "--id", "2099-01-01"]) == 1


def test_measure_sheet_publish_in_steps(tmp_path, monkeypatch, capsys):
    market = standard_market()
    monkeypatch.setattr(measure, "IndexReader", lambda: market.reader())
    monkeypatch.setattr(measure, "SafeFetcher", lambda: market.fetcher())
    key = tmp_path / "key.pem"
    main(["keygen", "--out", str(key)])
    monkeypatch.setenv("INSPECTOR_SIGNING_KEY", key.read_text())
    run_file, sheet_file = tmp_path / "run.json", tmp_path / "sheet.json"
    assert main(["measure", "--out", str(run_file), "--id", "2026-11-16"]) == 0
    assert main(["sheet", str(run_file), "--out", str(sheet_file)]) == 0
    assert main(["publish", str(tmp_path / "site"), str(sheet_file)]) == 0
    assert main(["publish", str(tmp_path / "site"), str(sheet_file)]) == 2     # once per id
    assert main(["verify", str(tmp_path / "site")]) == 0
