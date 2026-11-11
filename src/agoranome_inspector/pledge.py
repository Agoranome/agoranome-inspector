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

"""The 15% pledge in the open book.

Agoranome pledges 15% of what it earns to a public cause, paid once a month from its own receiving address to the
cause's public address in USDC on Base. The lab's pledge ledger (GET /impact/ledger) states each month's settled
revenue, the part that owes the pledge, what is owed, and the transfers made. A `pledge` entry copies those
figures into the book as read, with a hash of the page, so a past month cannot be quietly changed.

Three checks, all from the book alone except the last:

  1. owed = ceil(counted x pledge_bps / 10000) for each month, the lab's own rule.
  2. given = the sum of the month's verified transfers, and the month is "kept" exactly when given >= owed.
  3. With a Base RPC (verify --chain RPC), each transfer's transaction holds a USDC Transfer to the cause's
     address of at least its stated amount.

A month that owes under $1 carries over and shows as outstanding until the quarter's transfer. The figures are the
lab's: the inspector checks their arithmetic and the transfers, and anyone can check a receipt against the month's
root with verify-receipt.
"""

import json
from typing import Any, Callable, Dict, List, Optional

from agoranome_inspector.canonical import digest, sha256_hex

BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DEFAULT_BPS = 1500


def _int(value: Any) -> Optional[int]:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _address(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text if len(text) == 42 and text.startswith("0x") and all(c in "0123456789abcdef" for c in text[2:]) \
        else None


def _tx(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    return text if len(text) == 66 and text.startswith("0x") and all(c in "0123456789abcdef" for c in text[2:]) \
        else None


def months_in(ledger: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Each month's figures as the ledger shows them (its `periods`), in strict formats: whole numbers as strings,
    addresses and hashes as hex, nothing else. A month without figures (the ledger withholding them) is left out."""
    found = []
    for month in ledger.get("periods") or []:
        if not isinstance(month, dict) or not month.get("period"):
            continue
        counted, owed, given = (_int(month.get(k)) for k in ("counted_atomic", "owed_atomic", "given_atomic"))
        if counted is None or owed is None or given is None:
            continue
        transfers = []
        for d in month.get("donations") or []:
            if not isinstance(d, dict) or not _tx(d.get("tx_hash")) or _int(d.get("amount_atomic")) is None:
                continue
            transfers.append({"tx_hash": _tx(d["tx_hash"]), "amount_atomic": str(_int(d["amount_atomic"])),
                              "recipient": _address(d.get("recipient")), "verified": bool(d.get("verified"))})
        found.append({
            "period": str(month["period"])[:7],
            "merkle_root": str(month.get("merkle_root") or "").lower()[:66] or None,
            "receipts": _int(month.get("receipts")) or 0,
            "revenue_atomic": str(_int(month.get("revenue_atomic")) or 0),
            "counted_atomic": str(counted),
            "owed_atomic": str(owed),
            "given_atomic": str(given),
            "status": "kept" if month.get("status") == "kept" else "outstanding",
            "transfers": transfers,
        })
    return sorted(found, key=lambda m: m["period"])


def pledge_body(url: str, raw: bytes, read_at: str) -> Optional[Dict[str, Any]]:
    """The book entry's body for one reading of the ledger, or None when it shows no figures."""
    ledger = json.loads(raw, parse_float=str)
    months = months_in(ledger)
    if not months:
        return None
    terms = ledger.get("terms") if isinstance(ledger.get("terms"), dict) else {}
    bps = _int(ledger.get("pledge_bps")) or DEFAULT_BPS
    totals = {key: str(sum(int(m[f"{key}_atomic"]) for m in months))
              for key in ("revenue", "counted", "owed", "given")}
    return {
        "source": url, "read_at": read_at, "sha256": sha256_hex(raw),
        "pledge_bps": bps, "asset": BASE_USDC, "network": "eip155:8453",
        "recipient": _address(terms.get("recipient")),
        "months": months, "totals": totals,
        "outstanding_atomic": str(max(0, int(totals["owed"]) - int(totals["given"]))),
    }


def figures_digest(body: Dict[str, Any]) -> str:
    """What a reading says, without when it was read: two readings with the same digest need one entry."""
    return digest({k: body.get(k) for k in ("pledge_bps", "recipient", "months")})


def owed(counted_atomic: int, bps: int) -> int:
    """The lab's rule: the pledge's share of what counts, rounded up to the next atomic unit."""
    return -(-counted_atomic * bps // 10_000)


def check(body: Dict[str, Any]) -> List[str]:
    """What the figures in one pledge entry get wrong, if anything (checks 1 and 2)."""
    problems = []
    bps = _int(body.get("pledge_bps"))
    if bps is None or not 0 < bps <= 10_000:
        return [f"pledge_bps {body.get('pledge_bps')!r} is not a share"]
    for m in body.get("months") or []:
        where = f"pledge {m.get('period')}"
        counted, stated = int(m["counted_atomic"]), int(m["owed_atomic"])
        if stated != owed(counted, bps):
            problems.append(f"{where}: owes {owed(counted, bps)}, the ledger says {stated}")
        given = sum(int(t["amount_atomic"]) for t in m.get("transfers") or [] if t.get("verified"))
        if given != int(m["given_atomic"]):
            problems.append(f"{where}: its verified transfers add up to {given}, the ledger says {m['given_atomic']}")
        if (m.get("status") == "kept") != (int(m["given_atomic"]) >= stated):
            problems.append(f"{where}: status {m.get('status')} does not follow from given and owed")
    for key in ("revenue", "counted", "owed", "given"):
        total = sum(int(m[f"{key}_atomic"]) for m in body.get("months") or [])
        if str(total) != str((body.get("totals") or {}).get(key)):
            problems.append(f"pledge totals: {key} is {total}, the entry says {(body.get('totals') or {}).get(key)}")
    return problems


def _rpc(url: str, method: str, params: list, post: Callable[[str, bytes], bytes]) -> Any:
    raw = post(url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode())
    answer = json.loads(raw)
    if answer.get("error"):
        raise ValueError(str(answer["error"])[:200])
    return answer.get("result")


def check_transfers(body: Dict[str, Any], rpc: str, post: Callable[[str, bytes], bytes]) -> List[str]:
    """Check 3: each verified transfer is a USDC Transfer on Base to the stated recipient (the pledge's, when the
    ledger names one) of at least its amount."""
    problems = []
    for m in body.get("months") or []:
        for t in m.get("transfers") or []:
            if not t.get("verified"):
                continue
            to = body.get("recipient") or t.get("recipient")
            where = f"pledge {m['period']} transfer {t['tx_hash'][:10]}"
            if not to:
                problems.append(f"{where}: no recipient to check it against")
                continue
            try:
                receipt = _rpc(rpc, "eth_getTransactionReceipt", [t["tx_hash"]], post)
            except Exception as e:
                problems.append(f"{where}: the chain could not be read ({e})")
                continue
            if not receipt or receipt.get("status") not in ("0x1", 1):
                problems.append(f"{where}: no successful transaction on the chain")
                continue
            paid = 0
            for log in receipt.get("logs") or []:
                topics = [str(x).lower() for x in log.get("topics") or []]
                if (str(log.get("address", "")).lower() == BASE_USDC and len(topics) == 3
                        and topics[0] == TRANSFER_TOPIC and topics[2][-40:] == to[2:]):
                    paid += int(str(log.get("data") or "0x0"), 16)
            if paid < int(t["amount_atomic"]):
                problems.append(f"{where}: {paid} USDC units reached {to}, under the {t['amount_atomic']} stated")
    return problems


def http_post(url: str, data: bytes, timeout: float = 30.0) -> bytes:
    import urllib.request

    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                               "User-Agent": "agoranome-inspector verify"})
    with urllib.request.urlopen(request, timeout=timeout) as answer:   # noqa: S310 (an RPC the reader chose)
        return answer.read()


def usd(atomic: Any) -> str:
    value = int(str(atomic))
    return f"${value / 1_000_000:,.2f}" if value >= 10_000 else f"${value / 1_000_000:.6f}".rstrip("0")
