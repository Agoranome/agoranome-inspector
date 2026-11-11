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

"""The sheet: one row for each x402 listing with real demand, what it states, what it answered and the verdict.

Every row carries the inputs its verdict was judged from, so the verdict can be judged again by anyone. The
sheet's summary is counted from its rows alone, and its Merkle root (merkle.py) goes into the open book, so a
single row can be proven to belong to a published sheet.
"""

import csv
import io
from collections import Counter
from typing import Any, Dict, List, Optional

from agoranome_inspector import networks
from agoranome_inspector.bazaar import INDEX_URL, REAL_DEMAND_PAYERS, is_repeat_use
from agoranome_inspector.canonical import canonical
from agoranome_inspector.merkle import leaf_hash, merkle_root
from agoranome_inspector.rule import METHOD, RULE, RULES

KIND = "agoranome.x402-sheet"
FORMAT = 1
LICENCE = "CC BY 4.0"


def row(listing: Dict[str, Any], seen: Optional[Dict[str, Any]], *, publish_index_counts: bool = False,
        rule: str = RULE) -> Dict[str, Any]:
    out = {
        "resource": listing["resource"],
        "host": listing["host"],
        "category": listing["category"],
        "listed": listing["listed"],
        "seen": seen,
        "verdict": RULES[rule](listing["listed"], seen),
    }
    if publish_index_counts:
        out["index"] = {"payers_30d": listing["payers_30d"], "calls_30d": listing["calls_30d"],
                        "repeat_use": is_repeat_use(listing)}
    return out


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts over the rows, each key sorted so the summary is the same however the rows were read."""
    def name(value: Any) -> str:
        return "null" if value is None else str(value).lower()

    def count(key: str) -> Dict[str, int]:
        found = Counter(name(r["verdict"].get(key)) for r in rows)
        return dict(sorted(found.items()))

    return {
        "rows": len(rows),
        "hosts": len({r["host"] for r in rows}),
        "answer": count("answer"),
        "price": count("price"),
        "pay_to": count("pay_to"),
        "network": count("network"),
        "kept": count("kept"),
        "fair_offer": sum(1 for r in rows if (r.get("seen") or {}).get("fair_offer")),
    }


def leaves(sheet: Dict[str, Any]) -> List[str]:
    return [leaf_hash(r) for r in sheet["rows"]]


def root(sheet: Dict[str, Any]) -> Optional[str]:
    return merkle_root(leaves(sheet))


def build(sheet_id: str, listings: List[Dict[str, Any]], seen: Dict[str, Optional[Dict[str, Any]]], *,
          index: Dict[str, Any], probe: Dict[str, Any], publish_index_counts: bool = False,
          min_payers: int = REAL_DEMAND_PAYERS) -> Dict[str, Any]:
    """A sheet from the selected listings and what each answered (`seen`, keyed by resource; a listing missing
    from it was not asked in this run)."""
    rows = sorted((row(x, seen.get(x["resource"]), publish_index_counts=publish_index_counts) for x in listings),
                  key=lambda r: r["resource"])
    return {
        "kind": KIND,
        "format": FORMAT,
        "id": sheet_id,
        "rule": RULE,
        "method": METHOD,
        "licence": LICENCE,
        "selection": {
            "index": index.get("url") or INDEX_URL,
            "min_payers_30d": min_payers,
            "index_read_at": index.get("read_at"),
            "index_listings": index.get("total_reported"),
            "index_complete": bool(index.get("complete")),
            "index_digest": index.get("digest"),
            "index_counts_published": publish_index_counts,
        },
        "probe": probe,
        "rows": rows,
        "summary": summarize(rows),
    }


def to_bytes(sheet: Dict[str, Any]) -> bytes:
    """The published file: canonical JSON and a newline, so its SHA-256 is the same wherever it is rebuilt."""
    return canonical(sheet) + b"\n"


CSV_COLUMNS = ["resource", "host", "category", "answer", "price", "pay_to", "kept", "network", "listed_network",
               "listed_asset", "listed_amount", "listed_usd", "listed_pay_to", "asked_network", "asked_asset",
               "asked_amount", "asked_usd", "asked_pay_to", "fair_offer", "status", "seen_at", "leaf"]


def to_csv(sheet: Dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for r in sheet["rows"]:
        verdict, seen = r["verdict"], r.get("seen") or {}
        listed = (r.get("listed") or [None])[0] or {}
        asked = verdict.get("asked") or {}
        kept = verdict.get("kept")
        writer.writerow([
            r["resource"], r["host"], r["category"], verdict["answer"], verdict.get("price") or "",
            verdict.get("pay_to") or "", "" if kept is None else str(kept).lower(), verdict.get("network") or "",
            listed.get("network") or "", listed.get("asset") or "", listed.get("amount") or "",
            networks.usd(listed.get("network"), listed.get("asset"), listed.get("amount")) or "",
            listed.get("pay_to") or "", asked.get("network") or "", asked.get("asset") or "",
            asked.get("amount") or "",
            networks.usd(asked.get("network"), asked.get("asset"), asked.get("amount")) or "",
            asked.get("pay_to") or "", seen.get("fair_offer") or "", seen.get("status") or "", seen.get("at") or "",
            leaf_hash(r),
        ])
    return out.getvalue()
