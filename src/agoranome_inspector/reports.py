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

"""Buyers' reports in the open book.

The lab takes a report from a buyer that paid an x402 seller (POST /reports on api.agoranome.com): it names the
payment's transaction on Base, the transaction must move USDC from the reporting wallet to an address the seller's
row on this inspector's sheet asks payment to, and the wallet signs it (EIP-191). The lab lists them at
/reports.json. A report carries no free text, only its outcome.

`agoranome-inspector reports SITE` copies into the book every report the listing shows that the book doesn't hold
yet, in strict formats, with a hash of the page as read. From then on a report can't be quietly removed: one the
book holds that the lab's listing no longer shows is named in the next entry's `missing`. The verifier checks each
report against the pick table of the sheet it names (the pay-to was the row's), and with `--chain RPC` reads the
transaction again on Base. The signature can be checked with any EIP-191 library: the message is in the entry.

Reports are signs, not verdicts. No rule of this inspector counts them yet; pick-1 doesn't.
"""

import json
from typing import Any, Callable, Dict, Iterable, List, Optional, Set
from urllib.parse import urlsplit

from agoranome_inspector.canonical import sha256_hex

LAB_REPORTS = "https://api.agoranome.com/reports.json"
OUTCOMES = ("delivered", "not_delivered", "wrong_result", "charged_more", "too_slow")
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
FIELDS = ("tx", "resource", "host", "outcome", "payer", "pay_to", "amount_atomic", "block", "sheet", "signature",
          "reported_at")
MAX_REPORTS = 5000   # read from one listing; more waits for the next run


def _hex(value: Any, digits: int) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text if len(text) == digits + 2 and text.startswith("0x") and all(
        c in "0123456789abcdef" for c in text[2:]) else None


def _whole(value: Any) -> Optional[str]:
    text = str(value if value is not None else "").strip()
    return text if text.isdigit() and len(text) <= 40 else None


def message(resource: str, tx: str, outcome: str) -> str:
    """What the paying wallet signed (the lab's buyer_reports.message)."""
    return f"Agoranome buyer report\nResource: {resource}\nPayment: {tx}\nOutcome: {outcome}"


def strict(report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One report in the book's formats, or None when any field isn't what the lab's rules allow."""
    if not isinstance(report, dict):
        return None
    resource = str(report.get("resource") or "")
    host = (urlsplit(resource).hostname or "").lower() if resource.startswith("https://") else ""
    out = {
        "tx": _hex(report.get("tx"), 64), "resource": resource if host and len(resource) <= 2048 else None,
        "host": host or None, "outcome": report.get("outcome") if report.get("outcome") in OUTCOMES else None,
        "payer": _hex(report.get("payer"), 40), "pay_to": _hex(report.get("pay_to"), 40),
        "amount_atomic": _whole(report.get("amount_atomic")), "block": _whole(report.get("block")),
        "sheet": str(report.get("sheet") or "") or None, "signature": _hex(report.get("signature"), 130),
        "reported_at": str(report.get("reported_at") or "")[:20] or None,
    }
    if any(out[k] is None for k in FIELDS) or str(report.get("host") or host).lower() != host:
        return None
    if len(out["sheet"]) > 64 or not all(c.isalnum() or c in "-_." for c in out["sheet"]):
        return None
    return out


def held(entries: Iterable[Dict[str, Any]]) -> Set[str]:
    """Every payment the book holds a report for."""
    return {r["tx"] for e in entries if e.get("kind") == "reports" for r in e["body"].get("reports") or []}


def reports_body(url: str, raw: bytes, read_at: str, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The reports the listing shows that the book doesn't hold, and those the book holds that it no longer shows."""
    listing = json.loads(raw, parse_float=str)
    shown = listing.get("reports") if isinstance(listing, dict) else None
    if not isinstance(shown, list):
        raise ValueError("the lab's listing has no reports list")
    kept = held(entries)
    new: Dict[str, Dict[str, Any]] = {}
    refused = 0
    seen: Set[str] = set()
    for report in shown[:MAX_REPORTS]:
        found = strict(report)
        if found is None:
            refused += 1
            continue
        seen.add(found["tx"])
        if found["tx"] not in kept and found["tx"] not in new:
            new[found["tx"]] = found
    reports = sorted(new.values(), key=lambda r: (r["reported_at"], r["tx"]))
    missing = sorted(kept - seen) if len(shown) <= MAX_REPORTS else []
    return {"source": url, "read_at": read_at, "sha256": sha256_hex(raw), "listed": len(shown),
            "refused": refused, "reports": reports, "counts": counts(reports), "missing": missing,
            "held": len(kept) + len(reports)}


def counts(reports: List[Dict[str, Any]]) -> Dict[str, int]:
    return {o: sum(1 for r in reports if r["outcome"] == o) for o in OUTCOMES}


def check(body: Dict[str, Any], earlier: Iterable[Dict[str, Any]]) -> List[str]:
    """The entry's own figures: strict formats, no payment reported twice, counts that add up."""
    problems = []
    before = held(earlier)
    seen: Set[str] = set()
    for r in body.get("reports") or []:
        if strict(r) != r:
            problems.append(f"report {str(r.get('tx'))[:10]} is not in the book's formats")
            continue
        if r["tx"] in before or r["tx"] in seen:
            problems.append(f"payment {r['tx'][:10]} is reported twice")
        seen.add(r["tx"])
    if body.get("counts") != counts(body.get("reports") or []):
        problems.append("the counts don't match the reports")
    if body.get("held") != len(before) + len(body.get("reports") or []):
        problems.append("the number held doesn't match the book")
    if not set(body.get("missing") or []) <= before:
        problems.append("a payment named missing was never in the book")
    return problems


def check_rows(body: Dict[str, Any], table_for: Callable[[str], Optional[Dict[str, Any]]]) -> List[str]:
    """Each report's pay-to was one its resource's row asked payment to, on the pick table of the sheet it names."""
    problems = []
    for r in body.get("reports") or []:
        table = table_for(r["sheet"])
        where = f"report {r['tx'][:10]}"
        if table is None:
            problems.append(f"{where}: the book holds no pick table for {r['sheet']}")
            continue
        asked = {str((row.get("pay") or {}).get("pay_to") or "").lower() for row in table.get("rows") or []
                 if row.get("resource") == r["resource"]}
        if r["pay_to"] not in asked:
            problems.append(f"{where}: {r['sheet']} lists no such row asking payment to its pay-to")
    return problems


def check_transfers(body: Dict[str, Any], rpc: str, post: Callable[[str, bytes], bytes]) -> List[str]:
    """With a Base RPC: each payment is a successful transaction moving at least the amount in USDC from the payer
    to the pay-to."""
    from agoranome_inspector.pledge import _rpc

    problems = []
    for r in body.get("reports") or []:
        where = f"report {r['tx'][:10]}"
        try:
            receipt = _rpc(rpc, "eth_getTransactionReceipt", [r["tx"]], post)
        except Exception as e:
            problems.append(f"{where}: the chain could not be read ({e})")
            continue
        if not receipt or receipt.get("status") not in ("0x1", 1):
            problems.append(f"{where}: no successful transaction on the chain")
            continue
        paid = 0
        for log in receipt.get("logs") or []:
            topics = [str(x).lower() for x in log.get("topics") or []]
            if (str(log.get("address", "")).lower() == BASE_USDC and len(topics) == 3 and topics[0] == TRANSFER_TOPIC
                    and topics[1][-40:] == r["payer"][2:] and topics[2][-40:] == r["pay_to"][2:]):
                paid += int(str(log.get("data") or "0x0"), 16)
        if paid < int(r["amount_atomic"]):
            problems.append(f"{where}: {paid} USDC units moved from the payer to the pay-to, under the "
                            f"{r['amount_atomic']} stated")
    return problems


def read_reports(url: str = LAB_REPORTS, get: Optional[Callable[[str], bytes]] = None) -> bytes:
    if get is None:
        from agoranome_inspector.verify import http_get as get
    return get(url)
