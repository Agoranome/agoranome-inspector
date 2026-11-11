"""The record that travels (record.py): a host's rows on every sheet, checked from the file alone."""

import json

from agoranome_inspector import record
from agoranome_inspector.cli import main
from test_pick import published_site


def two_weeks(tmp_path, monkeypatch, capsys):
    site, kid = published_site(tmp_path, monkeypatch, capsys)
    assert main(["run", str(site), "--private", str(tmp_path / "p"), "--key-file", str(tmp_path / "key.pem"),
                 "--id", "2026-11-23", "--concurrency", "2"]) == 0
    capsys.readouterr()
    return site, kid


def test_a_record_carries_every_week_and_checks_from_the_file_alone(tmp_path, monkeypatch, capsys):
    site, kid = two_weeks(tmp_path, monkeypatch, capsys)
    out = tmp_path / "honest.json"
    assert main(["record", str(site), "honest.example", "--out", str(out)]) == 0
    said = json.loads(capsys.readouterr().out)
    assert said["weeks"] == 2 and said["sheets"] == 2 and said["rows"] >= 2
    found = json.loads(out.read_text())
    assert [w["sheet"] for w in found["weeks"]] == ["2026-11-16", "2026-11-23"]
    assert all(w["summary"]["payable_as_listed"] >= 1 for w in found["weeks"])
    assert record.check(found, pinned_kid=kid) == []
    assert main(["verify-record", str(out), f"--key={kid}", "--against", str(site)]) == 0
    assert "VERIFIED" in capsys.readouterr().out
    # The wrong first key, a changed row, a dropped row, a row of another host or a forged entry all fail.
    assert "not the pinned" in record.check(found, pinned_kid="someone-else")[0]
    changed = json.loads(out.read_text())
    changed["weeks"][0]["rows"][0]["row"]["verdict"]["matches_listing"] = False
    assert "does not fold" in record.check(changed)[0]
    other = json.loads(out.read_text())
    other["weeks"][0]["rows"][0]["row"]["host"] = "pricey.example"
    assert "another host" in record.check(other)[0]
    forged = json.loads(out.read_text())
    forged["weeks"][1]["entry"]["body"]["root"] = forged["weeks"][0]["entry"]["body"]["root"]
    assert "hash does not match" in record.check(forged)[0]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(changed))
    assert main(["verify-record", str(bad)]) == 1
    # A host on no sheet has no record.
    assert main(["record", str(site), "nowhere.example"]) == 2


def test_a_record_names_entries_the_live_book_no_longer_holds(tmp_path, monkeypatch, capsys):
    site, kid = two_weeks(tmp_path, monkeypatch, capsys)
    found = record.build(str(site), "honest.example")
    entries = [json.loads(line) for line in (site / "book.jsonl").read_text().splitlines()]
    assert record.check_against(found, entries) == []
    entries[found["weeks"][0]["entry"]["seq"]]["hash"] = "0x" + "00" * 32
    assert record.check_against(found, entries) == [f"entry {found['weeks'][0]['entry']['seq']} is not in the live "
                                                    "book as the record carries it"]
