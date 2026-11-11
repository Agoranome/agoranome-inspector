# Copyright 2026 Kamkar Foundation, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Best-buy sheets, the rule `best-buy-1`: one list per kind of job, the real price and the delivery signs side by side.

Built only from what the book already signed, so anyone can build it again:

  the newest pick table of each market    the endpoints in the running: what each asked when asked, honest on price
                                          or not, and whether it promises to settle only on delivery (Fair Offer)
  the newest signs file                   real and repeat payers of each x402 seller, read from the chain
  every buyers' report in the book        outcomes reported by wallets that paid, each tied to its payment

A kind of job is the listing's category, by the lab's keyword rules (the same as the sheet's). Within a category the
order is pick-1's without a job to match: honest on price first, then a promise to settle only on delivery, then the
lower price, then the address. Signs and reports are shown beside each row and never move it: a rule that ranks by
them will be a new rule with its own name. The page shows the first TOP of each category; the file holds every row.
No seller's words are shown, only its address, host and figures.
"""

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional

from agoranome_inspector.reports import OUTCOMES

RULE = "best-buy-1"
KIND = "agoranome.best-buy"
FORMAT = 1
TOP = 10
LABELS = {
    "documents": "PDF and OCR", "media": "Image, audio and video", "ai_models": "AI model access",
    "web_search": "Web search", "page_reading": "Page reading and scraping", "news": "News",
    "market_data": "Stocks and market data", "enrichment": "People and company enrichment",
    "weather_geo": "Weather and location", "chain_data": "On-chain data", "agent_tools": "Agent tools and MCP",
    "other": "Other",
}


def report_counts(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Each resource's reports by outcome, over every reports entry given."""
    out: Dict[str, Counter] = defaultdict(Counter)
    for e in entries:
        if e.get("kind") == "reports":
            for r in e["body"].get("reports") or []:
                out[r["resource"]][r["outcome"]] += 1
    return {k: {o: v[o] for o in OUTCOMES if v[o]} for k, v in out.items()}


def build(tables: List[Dict[str, Any]], signs_file: Optional[Dict[str, Any]], reports: Dict[str, Dict[str, int]],
          sources: Dict[str, Any]) -> Dict[str, Any]:
    """The best-buy file from pick tables, a signs file and report counts; `sources` names the entries read."""
    from agoranome_inspector.signs import by_host

    signs = by_host(signs_file)
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for table in tables:
        for r in table.get("rows") or []:
            row = {"resource": r["resource"], "host": r["host"], "market": r["market"],
                   "price_usd": r["price_usd"], "honest": r["honest"], "fair_offer": r["delivery"] == 0}
            s = signs.get(r["host"]) if r["market"] == "x402" else None
            if s:
                row["signs"] = {"real_payers": s["real_payers"], "repeat_payers": s["repeat_payers"]}
            if reports.get(r["resource"]):
                row["reports"] = reports[r["resource"]]
            groups[r.get("category") or "other"].append(row)
    categories = []
    for key in sorted(groups, key=lambda k: (list(LABELS).index(k) if k in LABELS else len(LABELS), k)):
        rows = sorted(groups[key], key=lambda r: (r["honest"], 0 if r["fair_offer"] else 1,
                                                  Decimal(r["price_usd"]), r["resource"]))
        categories.append({"category": key, "label": LABELS.get(key, key), "listings": len(rows),
                           "with_repeat_payers": sum(1 for r in rows if (r.get("signs") or {}).get("repeat_payers")),
                           "rows": rows})
    return {"kind": KIND, "format": FORMAT, "rule": RULE, "sources": sources, "categories": categories}


def inputs(entries: List[Dict[str, Any]], read) -> Optional[Dict[str, Any]]:
    """What the best-buy file is built from, as of the end of `entries`: the newest pick entry of each market, the
    newest signs entry for one of those sheets, and every reports entry. `read(entry)` loads an entry's file."""
    newest: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        if e.get("kind") == "pick":
            newest[e["body"].get("market")] = e
    if not newest:
        return None
    picks = sorted(newest.values(), key=lambda e: e["seq"])
    sheet_ids = {e["body"]["sheet"]["id"] for e in picks}
    signs_entry = next((e for e in reversed(entries) if e.get("kind") == "signs"
                        and (e["body"].get("sheet") or {}).get("id") in sheet_ids), None)
    reported = [e for e in entries if e.get("kind") == "reports"]
    sources = {"picks": [{"seq": e["seq"], "market": e["body"]["market"], "sheet": e["body"]["sheet"]["id"]}
                         for e in picks],
               "signs": {"seq": signs_entry["seq"], "sheet": signs_entry["body"]["sheet"]["id"]}
               if signs_entry else None,
               "reports_through": reported[-1]["seq"] if reported else None}
    return {"tables": [read(e) for e in picks], "signs": read(signs_entry) if signs_entry else None,
            "reports": report_counts(reported), "sources": sources}


def summary(found: Dict[str, Any]) -> Dict[str, Any]:
    return {"categories": len(found["categories"]),
            "listings": sum(c["listings"] for c in found["categories"]),
            "with_repeat_payers": sum(c["with_repeat_payers"] for c in found["categories"])}


HONEST = {0: "asked what it lists", 1: "not judged", 2: "asked more, or another pay-to"}


def page(found: Dict[str, Any], file: str) -> str:
    """best-buy/index.html: the first TOP rows of each category."""
    import html

    e = html.escape
    parts = []
    for c in found["categories"]:
        rows = "".join(
            f"<tr><td><code>{e(r['resource'])}</code></td><td>{e(r['market'])}</td><td>${e(r['price_usd'])}</td>"
            f"<td>{e(HONEST[r['honest']])}</td><td>{'yes' if r['fair_offer'] else ''}</td>"
            f"<td>{(r.get('signs') or {}).get('real_payers', '')}</td>"
            f"<td>{(r.get('signs') or {}).get('repeat_payers', '')}</td>"
            f"<td>{e(', '.join(f'{n} {o.replace(chr(95), chr(32))}' for o, n in (r.get('reports') or {}).items()))}"
            f"</td></tr>" for r in c["rows"][:TOP])
        parts.append(f"<h2>{e(c['label'])}</h2><p>{c['listings']:,} endpoints in the running, "
                     f"{c['with_repeat_payers']:,} with repeat payers on the chain.</p>"
                     f"<table><tr><th>Endpoint</th><th>Market</th><th>Price</th><th>Price honesty</th>"
                     f"<th>Settles only on delivery</th><th>Real payers (30 days)</th><th>Repeat payers</th>"
                     f"<th>Buyers' reports</th></tr>{rows}</table>")
    from agoranome_inspector import theme

    body = f"""<p class="eyebrow">Agoranome inspector</p>
<h1>Best buys, by kind of job</h1>
<p class="lead">For each kind of job, the paid endpoints in the running this week, in the order of the published rule
<code>{e(RULE)}</code>: honest on price first, then those that promise to settle only on delivery, then the lower price.
</p>
<p>Beside each, its delivery signs: real and repeat payers read from the Base chain over 30 days (x402 sellers),
and what paying buyers reported. Signs are shown, never ranked, and no seller can pay for a place. Every row is
built from the signed open book: <a href="../{e(file)}">the full list</a>, <a href="../index.html">the sheet</a>.</p>
{''.join(parts)}"""
    return theme.page("Agoranome: best buys by kind of job", body, depth=1, wide=True, current="best-buy")
