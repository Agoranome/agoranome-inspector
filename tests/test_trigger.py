"""The market count that reopens the wider build (reopen-1, the validation's item C7): hosts with 25 or more repeat
payers in the newest signs, against a bar of 50, counted into the book and counted again by the verifier."""

import json

from agoranome_inspector import pledge, trigger
from agoranome_inspector.book import Book
from agoranome_inspector.cli import main
from agoranome_inspector.keys import Signer

from test_signs import fake_rpc, market


def signs_file(repeat, *, pay_to=None, states=None, complete=True):
    """A signs file with one host per entry of `repeat`, its repeat payers that many."""
    hosts = []
    for i, n in enumerate(repeat):
        hosts.append({"host": f"h{i}.example", "pay_to": [(pay_to or {}).get(i) or "0x" + f"{i:040x}"],
                      "state": (states or {}).get(i, "counted"), "payments": n * 2, "payers": n,
                      "repeat_payers": n, "sweep_payers": 0, "self_payers": 0, "real_payers": n})
    return {"rule": "signs-1", "sheet": "2026-11-23", "complete": complete,
            "totals": {"hosts": len(hosts), "counted": sum(1 for h in hosts if h["state"] == "counted")},
            "hosts": hosts}


def entry(seq, body=None, kind="signs"):
    return {"seq": seq, "kind": kind, "body": body or {"sheet": {"seq": 1, "id": "2026-11-23"},
                                                      "file": "signs/2026-11-23.json", "sha256": "0x00",
                                                      "window": {"days": 30}}}


def test_a_host_counts_with_25_repeat_payers_and_the_bar_is_50_hosts():
    assert (trigger.MIN_REPEAT, trigger.HOSTS_NEEDED, trigger.RULE) == (25, 50, "reopen-1")
    found = signs_file([25, 24, 40, 0, 99], states={4: "busy"})
    got = trigger.count(found)
    # 24 is under the bar, and a host whose addresses were not all read is not counted at all.
    assert got["meeting"] == ["h0.example", "h2.example"] and got["hosts"] == 2 and got["counted"] == 4
    body = trigger.body_for(entry(5), found, [])
    assert body["met"] is False and body["first_met"] is None and body["hosts_needed"] == 50
    assert "50 x402 hosts" in body["text"] and "25 or more repeat payers" in body["text"]
    many = signs_file([25] * 49 + [10])
    assert trigger.body_for(entry(5), many, [])["met"] is False
    many = signs_file([25] * 50)
    body = trigger.body_for(entry(5), many, [])
    assert body["met"] is True and body["first_met"] == {"seq": 5, "sheet": "2026-11-23"}


def test_hosts_paid_to_one_wallet_are_one_seller_beside_the_count_never_in_it():
    found = signs_file([30] * 4, pay_to={0: "0x" + "aa" * 20, 1: "0x" + "aa" * 20})
    got = trigger.count(found)
    assert got["hosts"] == 4 and got["sellers"] == 3


def test_the_first_reading_that_met_the_bar_is_carried_forward_after_a_dip():
    met = trigger.body_for(entry(5), signs_file([25] * 50), [])
    dipped = trigger.body_for(entry(9), signs_file([25] * 49), [entry(6, met, "trigger")])
    assert dipped["met"] is False and dipped["first_met"] == {"seq": 5, "sheet": "2026-11-23"}
    again = trigger.body_for(entry(12), signs_file([25] * 60), [entry(6, met, "trigger"), entry(10, dipped, "trigger")])
    assert again["met"] is True and again["first_met"]["seq"] == 5


def test_the_count_goes_in_the_book_once_per_signs_file_and_is_counted_again(tmp_path, monkeypatch, capsys):
    from agoranome_inspector import measure

    m = market()
    monkeypatch.setattr(measure, "IndexReader", lambda: m.reader())
    monkeypatch.setattr(measure, "SafeFetcher", lambda: m.fetcher())
    monkeypatch.setattr(pledge, "http_post", fake_rpc())
    key = tmp_path / "key.pem"
    main(["keygen", "--out", str(key)])
    kid = json.loads(capsys.readouterr().out)["kid"]
    site = tmp_path / "site"
    assert main(["trigger", str(site), "--key-file", str(key)]) == 0     # no book yet: nothing to count
    assert json.loads(capsys.readouterr().out)["unchanged"] is True
    assert main(["run", str(site), "--private", str(tmp_path / "p"), "--key-file", str(key), "--id", "2026-11-16",
                 "--concurrency", "2"]) == 0
    capsys.readouterr()
    assert main(["trigger", str(site), "--key-file", str(key)]) == 0     # no signs yet
    assert json.loads(capsys.readouterr().out)["unchanged"] is True
    assert main(["signs", str(site), "--rpc", "https://rpc.example", "--key-file", str(key)]) == 0
    capsys.readouterr()
    assert main(["trigger", str(site), "--key-file", str(key)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["hosts"], out["needed"], out["met"], out["first_met"]) == (0, 50, False, None)
    assert ".example" not in json.dumps(out)
    assert main(["trigger", str(site), "--key-file", str(key)]) == 0
    assert json.loads(capsys.readouterr().out)["unchanged"] is True
    page = (site / "index.html").read_text()
    assert "The market count" in page and "<strong>not met</strong>" in page and "reopen-1" in page
    assert main(["verify", str(site), f"--key={kid}", "--json"]) == 0
    checks = {c["check"]: c for c in json.loads(capsys.readouterr().out)["checks"]}
    found = next(c for name, c in checks.items() if name.startswith("market count"))
    assert found["ok"] and "0 of 50 hosts" in found["detail"]
    # A count the signs file doesn't give is found, even signed with the book's own key.
    book = Book(str(site / "book.jsonl"))
    last = [e for e in book.entries() if e["kind"] == "trigger"][-1]
    book.append(Signer.load(str(key)), "trigger", {**last["body"], "hosts": 50, "met": True})
    assert main(["verify", str(site), f"--key={kid}", "--json"]) == 1
    checks = json.loads(capsys.readouterr().out)["checks"]
    bad = [c for c in checks if c["check"].startswith("market count") and not c["ok"]]
    assert bad and "does not follow from its signs file" in bad[0]["detail"]
