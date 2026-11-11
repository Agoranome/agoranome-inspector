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
from agoranome_inspector.verify import verify


def top(counter: Counter, n: int = 8) -> dict:
    return dict(counter.most_common(n))


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

    with tempfile.TemporaryDirectory() as site:
        publish(site, built, Signer.generate())
        checked = verify(site)
        report["verify"] = {"ok": checked.ok, "checks": [c["check"] + (" PASS" if c["ok"] else " FAIL")
                                                         for c in checked.checks]}
        report["sheet_bytes_per_row"] = round(len(sheet_lib.to_bytes(built)) / max(1, len(built["rows"])))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
