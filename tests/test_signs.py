"""Delivery signs from the chain (signs-1): payers, repeat payers, sweeps and self payers per x402 seller."""

import json

from agoranome_inspector import pledge, signs
from agoranome_inspector.cli import main

from fakes import Market, honest, item

HEAD = 2_000_000
END = HEAD - signs.FINALITY
HOSTS = [f"h{i}.example" for i in range(1, 8)]
ADDR = {h: "0x" + f"{i:02d}" * 20 for i, h in enumerate(HOSTS, start=1)}
SHARED = "0x" + "ee" * 20
BUYER, ONCE, BOT = "0x" + "b1" * 20, "0x" + "b2" * 20, "0x" + "b3" * 20


def market() -> Market:
    items = [item(f"https://{h}/search", "5000", pay_to=ADDR[h]) for h in HOSTS]
    items += [item(f"https://{h}/search", "5000", pay_to=SHARED) for h in ("p1.example", "p2.example")]
    sellers = {h: honest("5000", ADDR[h]) for h in HOSTS}
    sellers.update({h: honest("5000", SHARED) for h in ("p1.example", "p2.example")})
    return Market(items, sellers)


def chain_logs():
    """h1: one buyer back in a second session, one buyer once, and h1 paying itself; a bot pays all seven once
    within the hour (a sweep everywhere); the shared address takes payments that count for nobody."""
    def log(block, frm, to):
        return {"blockNumber": hex(block), "topics": [pledge.TRANSFER_TOPIC, signs._topic(frm), signs._topic(to)],
                "address": pledge.BASE_USDC, "data": "0x01"}
    h1 = ADDR["h1.example"]
    found = [log(END - 100_000, BUYER, h1), log(END - 50_000, BUYER, h1), log(END - 49_990, BUYER, h1),
             log(END - 30_000, ONCE, h1), log(END - 20_000, h1, h1), log(END - 10, ONCE, SHARED)]
    found += [log(END - 5_000 + i * 60, BOT, ADDR[h]) for i, h in enumerate(HOSTS)]
    found.append(log(END - 2_000_000, ONCE, ADDR["h2.example"]))     # before the window
    return found


def fake_rpc(limit=5_000, calls=None):
    logs = chain_logs()

    def post(url, data):
        req = json.loads(data)
        if calls is not None:
            calls.append(req["method"])
        if req["method"] == "eth_blockNumber":
            return json.dumps({"result": hex(HEAD)}).encode()
        q = req["params"][0]
        lo, hi = int(q["fromBlock"], 16), int(q["toBlock"], 16)
        if hi - lo + 1 > limit:
            return json.dumps({"error": {"code": -32005, "message": "range too large"}}).encode()
        wanted = set(q["topics"][2])
        hits = [x for x in logs if lo <= int(x["blockNumber"], 16) <= hi and x["topics"][2] in wanted]
        return json.dumps({"result": hits}).encode()
    return post


def sheet_of(site):
    entries = [json.loads(line) for line in (site / "book.jsonl").read_text().splitlines()]
    return entries, json.loads((site / next(e for e in entries if e["kind"] == "sheet")["body"]["file"]).read_text())


def test_signs_are_counted_from_the_chain_into_the_book_and_verified(tmp_path, monkeypatch, capsys):
    from agoranome_inspector import measure

    m = market()
    monkeypatch.setattr(measure, "IndexReader", lambda: m.reader())
    monkeypatch.setattr(measure, "SafeFetcher", lambda: m.fetcher())
    calls = []
    monkeypatch.setattr(pledge, "http_post", fake_rpc(calls=calls))
    key = tmp_path / "key.pem"
    main(["keygen", "--out", str(key)])
    kid = json.loads(capsys.readouterr().out)["kid"]
    site = tmp_path / "site"
    assert main(["run", str(site), "--private", str(tmp_path / "p"), "--key-file", str(key), "--id", "2026-11-16",
                 "--concurrency", "2"]) == 0
    capsys.readouterr()
    assert main(["signs", str(site), "--rpc", "https://rpc.example", "--private", str(tmp_path / "p"),
                 "--key-file", str(key)]) == 0
    out = json.loads(capsys.readouterr().out)
    # Counts only in the log: no host, no address.
    assert ".example" not in json.dumps(out) and "0x" not in json.dumps(out)
    assert out["totals"] == {"hosts": 9, "counted": 7, "platform": 2, "busy": 0, "not_read": 0,
                             "with_real_payers": 1, "with_repeat_payers": 1}
    found = json.loads((site / "signs" / "2026-11-16.json").read_text())
    h1 = signs.by_host(found)["h1.example"]
    assert (h1["payments"], h1["payers"], h1["repeat_payers"], h1["sweep_payers"], h1["self_payers"],
            h1["real_payers"]) == (6, 4, 1, 1, 1, 2)
    h2 = signs.by_host(found)["h2.example"]
    assert (h2["payers"], h2["sweep_payers"], h2["real_payers"]) == (1, 1, 0)     # the old payment is outside
    assert {h["host"]: h["state"] for h in found["hosts"]}["p1.example"] == "platform"
    assert found["window"] == {"from_block": END - 30 * signs.BLOCKS_PER_DAY + 1, "to_block": END, "days": 30}
    # The RPC refused 10,000 blocks, so the reader went on in halves.
    assert calls.count("eth_getLogs") > 1
    # Once per sheet.
    assert main(["signs", str(site), "--rpc", "https://rpc.example", "--key-file", str(key)]) == 0
    assert json.loads(capsys.readouterr().out)["unchanged"] is True
    assert main(["verify", str(site), f"--key={kid}", "--json", "--chain", "https://rpc.example"]) == 0
    checks = {c["check"]: c for c in json.loads(capsys.readouterr().out)["checks"]}
    assert checks["signs 2026-11-16"]["ok"] and "7 of 9 sellers counted" in checks["signs 2026-11-16"]["detail"]


def test_a_signs_file_that_does_not_follow_its_sheet_is_found(tmp_path, monkeypatch, capsys):
    from agoranome_inspector import measure

    m = market()
    monkeypatch.setattr(measure, "IndexReader", lambda: m.reader())
    monkeypatch.setattr(measure, "SafeFetcher", lambda: m.fetcher())
    key = tmp_path / "key.pem"
    main(["keygen", "--out", str(key)])
    site = tmp_path / "site"
    assert main(["run", str(site), "--private", str(tmp_path / "p"), "--key-file", str(key), "--id", "2026-11-16",
                 "--concurrency", "2"]) == 0
    _, sheet = sheet_of(site)
    reader = signs.ChainReader("https://rpc.example", fake_rpc(limit=10 ** 9), pause=0)
    found = signs.build(sheet, reader)
    assert signs.check_file(found, sheet) == []
    assert signs.recheck(found, reader) == []
    bad = json.loads(json.dumps(found))
    bad["hosts"][0]["pay_to"] = ["0x" + "99" * 20]
    assert any("pay-to addresses" in p for p in signs.check_file(bad, sheet))
    bad = json.loads(json.dumps(found))
    first = next(h for h in bad["hosts"] if h["state"] == "counted")
    first["real_payers"] += 1
    assert any("hang together" in p for p in signs.check_file(bad, sheet))
    lied = json.loads(json.dumps(found))
    next(h for h in lied["hosts"] if h["host"] == "h1.example")["payers"] = 9
    assert any("the chain shows" in p for p in signs.recheck(lied, reader, n=9))
    # Out of time before any read: every host is left "not_read", and the file says it is incomplete.
    late = signs.build(sheet, reader, budget_seconds=1, clock=iter([0, 5, 5, 5, 5, 5, 5, 5]).__next__)
    assert not late["complete"] and late["totals"]["not_read"] == 7
