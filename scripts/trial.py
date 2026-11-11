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
from urllib.parse import urlsplit

from agoranome_inspector import mpp
from agoranome_inspector import rule_mpp
from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.checks import before_signing
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
            schemes[d.get("scheme") or d.get("intent") or ""] += 1
            if d["price"] != "as_listed":
                ratios[_ratio(d["asked_amount"], d["listed_amount"])] += 1
    return {"rows": len(rows), "shapes": dict(shapes.most_common()), "ratios": top(ratios, 15),
            "differing_schemes": top(schemes), "listed_options_per_row": top(options, 10)}


def _differing(rows: list) -> list:
    return [r for r in rows if r["verdict"]["answer"] == "payable"
            and (r["verdict"]["price"] not in ("as_listed", "not_listed")
                 or r["verdict"]["pay_to"] not in ("as_listed", "not_listed"))]


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


def _dropped(options: list, keys: tuple) -> int:
    """Live options with an amount whose other fields were dropped by the strict formats."""
    return sum(1 for o in options if o.get("amount") and any(o.get(k) is None for k in keys))


def _sample(listings: list, n: int, per_host: int, seed: int) -> list:
    rng = random.Random(seed)
    shuffled = listings[:]
    rng.shuffle(shuffled)
    count: Counter = Counter()
    out = []
    for x in shuffled:
        if count[x["host"]] < per_host:
            out.append(x)
            count[x["host"]] += 1
        if len(out) >= n:
            break
    return out


def _verify(built: dict) -> dict:
    with tempfile.TemporaryDirectory() as site:
        publish(site, built, Signer.generate())
        checked = verify(site)
        return {"ok": checked.ok, "checks": [c["check"] + (" PASS" if c["ok"] else " FAIL") for c in checked.checks],
                "sheet_bytes_per_row": round(len(sheet_lib.to_bytes(built)) / max(1, len(built["rows"])))}


WORDS = ("required", "missing", "invalid", "validation", "expected", "must", "body", "param", "query", "field",
         "schema", "json", "payment", "unauthorized", "api key", "apikey", "token", "not allowed")


def _family(headers) -> str:
    kind = (headers.get("content-type") or "").lower()
    for name in ("json", "html", "text"):
        if name in kind:
            return name
    return "other" if kind else "none"


def _operation(spec, listing):
    paths = spec.get("paths") if isinstance(spec, dict) else None
    if not isinstance(paths, dict):
        return None
    path = urlsplit(listing["url"]).path or "/"
    for key, item in paths.items():
        if isinstance(item, dict) and (key == path or path.endswith(key)):
            op = item.get(listing["http_method"].lower())
            return op if isinstance(op, dict) else None
    return None


def _why_4xx(sample, seen, fetcher, limit=150) -> dict:
    """Why MPP endpoints answer 4xx to an unpaid ask: counts only, nothing named or kept."""
    rows = [x for x in sample if (seen.get(x["resource"]) or {}).get("status") not in (None, 402, 404, 410)
            and 400 <= (seen.get(x["resource"]) or {}).get("status") < 500][:limit]
    out = {"rows": len(rows), "status": Counter(), "http_method": Counter(), "dynamic": Counter(),
           "intent": Counter(), "content_type": Counter(), "words": Counter(), "post_without_body": Counter(),
           "openapi": Counter()}
    specs = {}
    for x in rows:
        listed = x["listed"][0]
        out["status"][str(seen[x["resource"]]["status"])] += 1
        out["http_method"][x["http_method"]] += 1
        out["dynamic"][str(listed.get("dynamic"))] += 1
        out["intent"][str(listed.get("intent"))] += 1
        try:
            f = fetcher.fetch(x["url"], x["http_method"], {} if x["http_method"] == "POST" else None)
            out["content_type"][_family(f.headers)] += 1
            text = (f.body or b"")[:4096].decode("utf-8", "replace").lower()
            for w in WORDS:
                if w in text:
                    out["words"][w] += 1
        except Exception as e:  # noqa: BLE001 - a diagnostic count
            out["content_type"]["error " + type(e).__name__] += 1
        if x["http_method"] == "POST":
            try:
                out["post_without_body"][str(fetcher.fetch(x["url"], "POST", None).status)] += 1
            except Exception as e:  # noqa: BLE001
                out["post_without_body"]["error " + type(e).__name__] += 1
        host = x["host"]
        if host not in specs and len(specs) < 60:
            try:
                f = fetcher.fetch(f"https://{host}/openapi.json", "GET")
                specs[host] = json.loads(f.body) if f.status == 200 else None
            except Exception:  # noqa: BLE001
                specs[host] = None
        spec = specs.get(host)
        if host not in specs:
            out["openapi"]["host not tried"] += 1
        elif spec is None:
            out["openapi"]["no spec"] += 1
        else:
            op = _operation(spec, x)
            if op is None:
                out["openapi"]["spec, operation not found"] += 1
            else:
                dumped = json.dumps(op)
                out["openapi"]["operation found"] += 1
                if op.get("requestBody"):
                    out["openapi"]["with requestBody"] += 1
                if op.get("parameters"):
                    out["openapi"]["with parameters"] += 1
                if '"example' in dumped:
                    out["openapi"]["with an example"] += 1
                if "x-payment-info" in dumped:
                    out["openapi"]["with x-payment-info"] += 1
    return {k: (top(v, 20) if isinstance(v, Counter) else v) for k, v in out.items()}


def _catalog_keys(raw) -> dict:
    services = [s for s in raw.get("services") or [] if isinstance(s, dict)]
    endpoints = [e for s in services for e in s.get("endpoints") or [] if isinstance(e, dict)]
    pays = [e["payment"] for e in endpoints if isinstance(e.get("payment"), dict)]
    return {"service": top(Counter(k for s in services for k in s), 30),
            "endpoint": top(Counter(k for e in endpoints for k in e), 30),
            "payment": top(Counter(k for p in pays for k in p), 30)}


def trial_mpp(args) -> None:
    """The MPP catalog, asked unpaid: counts only, no service named."""
    t0 = time.monotonic()
    catalog = mpp.CatalogReader().read()
    listings = catalog["listings"]
    listed = [x["listed"][0] for x in listings]
    report = {"catalog": {"seconds": round(time.monotonic() - t0), "services": catalog["services"],
                          "paid_endpoints": len(listings), "hosts": len({x["host"] for x in listings}),
                          "skipped": catalog["skipped"],
                          "listed_methods": top(Counter(o["method"] for o in listed)),
                          "listed_intents": top(Counter(o["intent"] for o in listed)),
                          "listed_currencies": top(Counter(o["currency"] for o in listed), 5),
                          "dynamic": sum(1 for o in listed if o["dynamic"]),
                          "http_methods": top(Counter(x["http_method"] for x in listings)),
                          "categories": top(Counter(x["category"] for x in listings), 12)}}
    sample = _sample(listings, args.sample, args.per_host, args.seed)
    fetcher = SafeFetcher()
    settings = Settings(concurrency=12, per_host=args.per_host, host_pause=0.5, budget_seconds=args.budget)
    t1 = time.monotonic()
    seen = ask_all(sample, fetcher, settings, asker=lambda x: mpp.probe(fetcher, x),
                   again=lambda x: mpp.ask(fetcher, x), judge_fn=rule_mpp.judge)
    built = mpp.build({"id": "mpp-trial", "catalog": {"url": catalog["url"], "read_at": None},
                       "probe": {"trial": True}, "listings": sample, "seen": seen})
    observed = [s for s in seen.values() if s]
    report["probe"] = {"sample": len(sample), "asked": len(seen), "seconds": round(time.monotonic() - t1),
                       "status": top(Counter(str(s.get("status")) for s in observed), 12),
                       "where": top(Counter(str(s.get("where")) for s in observed)),
                       "errors": top(Counter(str(s.get("error")) for s in observed if s.get("error"))),
                       "also_x402": sum(1 for s in observed if s.get("also_x402")),
                       "challenges_per_answer": top(Counter(len(s["options"]) for s in observed)),
                       "live_methods": top(Counter(o.get("method") for s in observed for o in s["options"])),
                       "live_intents": top(Counter(o.get("intent") for s in observed for o in s["options"])),
                       "options_with_a_dropped_field": sum(
                           _dropped(s["options"], ("method", "intent", "currency", "recipient")) for s in observed)}
    report["sheet"] = built["summary"]
    report["mismatches"] = mismatches(built)
    report["mismatching_hosts"] = len({r["host"] for r in _differing(built["rows"])})
    report["check_before_signing"] = before_signing(built)
    report["verify"] = _verify(built)
    report["why_4xx"] = _why_4xx(sample, seen, fetcher)
    try:
        report["catalog_keys"] = _catalog_keys(json.loads(mpp.CatalogReader().client.get(mpp.CATALOG_URL).content))
    except Exception as e:  # noqa: BLE001
        report["catalog_keys"] = {"error": type(e).__name__}
    print(json.dumps(report, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=("x402", "mpp"), default="x402")
    p.add_argument("--sample", type=int, default=400)
    p.add_argument("--per-host", type=int, default=2)
    p.add_argument("--budget", type=float, default=900)
    p.add_argument("--seed", type=int, default=402)
    args = p.parse_args()
    if args.market == "mpp":
        trial_mpp(args)
        return

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

    sample = _sample(chosen, args.sample, args.per_host, args.seed)

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
                       "live_schemes": top(Counter(o.get("scheme") for s in observed for o in s["options"])),
                       "options_with_a_dropped_field": sum(
                           _dropped(s["options"], ("scheme", "network", "asset", "pay_to")) for s in observed),
                       "listed_options_with_a_dropped_field": sum(_dropped(x["listed"], ("network", "asset"))
                                                                  for x in sample)}
    report["sheet"] = built["summary"]
    report["mismatches"] = mismatches(built)
    report["why"] = why(built)
    report["check_before_signing"] = before_signing(built)
    report["verify"] = _verify(built)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
