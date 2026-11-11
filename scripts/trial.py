"""A trial run against the live market that publishes nothing.

Reads the whole index, keeps the listings with real demand, asks a random sample of them without paying (at
most two per seller), judges them, signs a sheet into a temporary site with a throwaway key and verifies it.
It prints counts only: no seller is named, no file is kept, nothing is uploaded.

  python scripts/trial.py --sample 400 --budget 900
"""

import argparse
import json
import random
import tempfile
import time
from collections import Counter

from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.bazaar import IndexReader, select
from agoranome_inspector.fetch import SafeFetcher
from agoranome_inspector.keys import Signer
from agoranome_inspector.measure import Settings, ask_all
from agoranome_inspector.publish import publish
from agoranome_inspector.rule import _once, answer
from agoranome_inspector.verify import verify


def top(counter: Counter, n: int = 8) -> dict:
    return dict(counter.most_common(n))


def _ratio(asked: str, listed: str) -> str:
    a, b = int(asked), int(listed)
    if not b:
        return "listed 0"
    r = a / b
    return f"{r:.3g}x"


def mismatches(built: dict) -> dict:
    """Every row whose price or pay-to is not as listed, by shape: the verdicts, how many listed options it has, and
    for each differing option its scheme and the ratio of the live amount to the listed one. Counts and shapes
    only; no host or URL is printed."""
    rows = _differing(built["rows"])
    shapes, ratios, schemes, options = Counter(), Counter(), Counter(), Counter()
    for r in rows:
        v = r["verdict"]
        shapes[f"{v['price']} / {v['pay_to']} / asked twice: {r['seen'].get('again') is not None}"] += 1
        options[len(r["listed"])] += 1
        for d in v["differs"]:
            schemes[d.get("scheme") or ""] += 1
            if d["price"] != "as_listed":
                ratios[_ratio(d["asked_amount"], d["listed_amount"])] += 1
    return {"rows": len(rows), "shapes": dict(shapes.most_common()), "ratios": top(ratios, 15),
            "differing_schemes": top(schemes), "listed_options_per_row": top(options, 10)}


def _differing(rows: list) -> list:
    return [r for r in rows if r["verdict"]["answer"] == "payable"
            and (r["verdict"]["price"] not in ("as_listed", "not_listed") or r["verdict"]["pay_to"] != "as_listed")]


def _power_of_ten(asked: str, listed: str) -> bool:
    a, b = int(asked), int(listed)
    if not a or not b:
        return False
    big, small = max(a, b), min(a, b)
    return big % small == 0 and str(big // small).strip("0") == "1"


def why(built: dict) -> dict:
    """Why rows differ, in counts only: is a different pay-to the same address both times, an address the listing
    names on another option, a difference of letter case only; is a different price the same both times, a power
    of ten off, the same ratio on every option of the row; and how a looser check (the lab's: the first listed
    address against every live address, case ignored) would have judged the pay-to rows."""
    rows = _differing(built["rows"])
    pay, price, row_kinds = Counter(), Counter(), Counter()
    for r in rows:
        v, seen = r["verdict"], r["seen"]
        listed_to = [o.get("pay_to") for o in r["listed"] if o.get("pay_to")]
        live_to = [o["pay_to"] for o in seen.get("options") or [] if o.get("pay_to")]
        again = seen.get("again")
        second = _once(r["listed"], again)["differs"] if again and answer(again) == "payable" else []
        by_key = {(d["network"], d["asset"], d["scheme"], d["listed_amount"]): d for d in second}
        ratios = set()
        compared = len([o for o in r["listed"] if o.get("network") and o.get("asset") and o.get("amount")])
        row_kinds[f"differing options: {len(v['differs'])} of {compared} listed"] += 1
        row_kinds[f"category {r['category']}"] += 1
        row_kinds[f"answered on {seen.get('method')}, x402 v{seen.get('x402')}"] += 1
        if v["pay_to"] == "different" and listed_to:
            first = listed_to[0].lower()
            row_kinds["pay-to row the lab's looser check would also flag"
                      if first not in {a.lower() for a in live_to} else
                      "pay-to row the lab's looser check would pass"] += 1
            named = len(set(live_to))
            row_kinds[f"pay-to row, live addresses in the offer: {'3 or more' if named >= 3 else named}"] += 1
        for d in v["differs"]:
            d2 = by_key.get((d["network"], d["asset"], d["scheme"], d["listed_amount"]))
            if d["pay_to"] == "different":
                pay[f"network {d['network'].split(':')[0]}"] += 1
                a, b = d["asked_pay_to"], d["listed_pay_to"] or ""
                if a.lower() == b.lower():
                    pay["letter case only"] += 1
                if a in listed_to:
                    pay["live address is listed on another option"] += 1
                if b in live_to:
                    pay["listed address is live on another option"] += 1
                if len(a) != len(b):
                    pay["live and listed addresses differ in length"] += 1
                pay["second ask: same live address" if d2 and d2["asked_pay_to"] == a else
                    "second ask: another live address" if d2 else "second ask: option not differing"] += 1
            if d["price"] != "as_listed":
                ratios.add(_ratio(d["asked_amount"], d["listed_amount"]))
                price[f"{d['price']}"] += 1
                if _power_of_ten(d["asked_amount"], d["listed_amount"]):
                    price["a power of ten off"] += 1
                if d["listed_amount"] in {str(o.get("amount")) for o in seen.get("options") or []}:
                    price["listed amount is live on another option"] += 1
                if d["price"] == "above_listed":
                    price["second ask: same live amount" if d2 and d2["asked_amount"] == d["asked_amount"] else
                          "second ask: another live amount" if d2 else "second ask: option not differing"] += 1
        if len(ratios) == 1 and len([d for d in v["differs"] if d["price"] != "as_listed"]) > 1:
            price["row with one ratio on several options"] += 1
    return {"hosts": len({r["host"] for r in rows}), "rows": dict(row_kinds.most_common(24)),
            "pay_to_options": dict(pay.most_common()), "price_options": dict(price.most_common())}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sample", type=int, default=400)
    p.add_argument("--per-host", type=int, default=2)
    p.add_argument("--budget", type=float, default=900)
    p.add_argument("--seed", type=int, default=402)
    args = p.parse_args()

    t0 = time.monotonic()
    index = IndexReader().read()
    t_index = time.monotonic() - t0
    listings = index["listings"]
    chosen = select(listings)
    listed_ok = [x for x in chosen if any(o.get("network") and o.get("asset") and o.get("amount") for o in x["listed"])]
    report = {
        "index": {"total_reported": index["total_reported"], "read": len(listings), "complete": index["complete"],
                  "seconds": round(t_index), "with_real_demand": len(chosen),
                  "hosts_with_real_demand": len({x["host"] for x in chosen}),
                  "https": sum(1 for x in chosen if x["resource"].startswith("https://")),
                  "with_usable_listed_price": len(listed_ok),
                  "listed_networks": top(Counter(o.get("network") for x in chosen for o in x["listed"][:1])),
                  "listed_schemes": top(Counter(o.get("scheme") for x in chosen for o in x["listed"][:1])),
                  "categories": top(Counter(x["category"] for x in chosen), 12)},
    }

    rng = random.Random(args.seed)
    shuffled = chosen[:]
    rng.shuffle(shuffled)
    per_host: Counter = Counter()
    sample = []
    for x in shuffled:
        if per_host[x["host"]] < args.per_host:
            sample.append(x)
            per_host[x["host"]] += 1
        if len(sample) >= args.sample:
            break

    t1 = time.monotonic()
    seen = ask_all(sample, SafeFetcher(), Settings(concurrency=12, per_host=args.per_host, host_pause=0.5,
                                                   budget_seconds=args.budget))
    t_probe = time.monotonic() - t1
    built = sheet_lib.build("trial", sample, seen, index={**index, "read_at": None}, probe={"trial": True})
    observed = [s for s in seen.values() if s]
    report["probe"] = {"sample": len(sample), "asked": len(seen), "seconds": round(t_probe),
                       "where": top(Counter(str(s.get("where")) for s in observed)),
                       "x402": top(Counter(str(s.get("x402")) for s in observed)),
                       "status": top(Counter(str(s.get("status")) for s in observed), 12),
                       "errors": top(Counter(str(s.get("error")) for s in observed if s.get("error"))),
                       "asked_twice": sum(1 for s in observed if s.get("attempts") == 2),
                       "live_schemes": top(Counter(o.get("scheme") for s in observed for o in s["options"]))}
    report["sheet"] = built["summary"]
    report["mismatches"] = mismatches(built)
    report["why"] = why(built)

    with tempfile.TemporaryDirectory() as site:
        publish(site, built, Signer.generate())
        checked = verify(site)
        report["verify"] = {"ok": checked.ok, "checks": [c["check"] + (" PASS" if c["ok"] else " FAIL")
                                                         for c in checked.checks]}
        report["sheet_bytes_per_row"] = round(len(sheet_lib.to_bytes(built)) / max(1, len(built["rows"])))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
