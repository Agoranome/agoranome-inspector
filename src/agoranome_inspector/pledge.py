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

Small sums, the rule `carry-1`: a month that owes under $1 carries over, and the book shows it as owed. Nothing is
carried past the end of a quarter. `standing` runs that rule over the months, as a running balance of what was owed
less what was given: each month is "kept" (nothing left owing), "carried" (under $1 left, inside the quarter), or
"owed" (a transfer is due). Once a cause is named, a month still owed more than GRACE_DAYS after it ends, or a
quarter that ends with anything left, is "late", and the verifier says so. When the lab states its own standing for
a month, it must match.

When the book has closed a month (accounts.py), the month owes the close's total, every source together, and not the
lab's x402 figure alone. The figures are the lab's: the inspector checks their arithmetic and the transfers, and
anyone can check a receipt against the month's root with verify-receipt.
"""

import json
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from agoranome_inspector.canonical import digest, sha256_hex

BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DEFAULT_BPS = 1500
CARRY_RULE = "carry-1"
CARRY_UNDER = 1_000_000     # $1 in USDC's six decimals: a balance under this carries inside a quarter
GRACE_DAYS = 45             # the lab's pledge ledger's grace after a month ends (pledge_check.GRACE_DAYS)
STANDINGS = ("kept", "carried", "owed")


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
        if month.get("standing") in STANDINGS:
            found[-1]["standing"] = month["standing"]
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
    return problems + check_standing(body)


def _month_end(period: str) -> date:
    year, month = int(period[:4]), int(period[5:7])
    return (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))


def quarter_of(period: str) -> str:
    return f"{period[:4]}-Q{(int(period[5:7]) - 1) // 3 + 1}"


def quarter_ends(period: str) -> bool:
    return int(period[5:7]) % 3 == 0


def _quarter_end(period: str) -> date:
    month = ((int(period[5:7]) - 1) // 3 + 1) * 3
    return _month_end(f"{period[:4]}-{month:02d}")


def standing(months: List[Dict[str, Any]], *, as_of: Optional[str] = None, cause_named: bool = False,
             grace_days: int = GRACE_DAYS, owed_by_period: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """The rule carry-1 over the months, in order: what each owed (a close's total where the book closed it), what
    was given in it, the balance left after it, and its standing. With `as_of` (a date) and a cause named, a month
    still owed past its grace, or any balance left after its quarter's grace, is "late"."""
    owed_by_period = owed_by_period or {}
    today = date.fromisoformat(as_of[:10]) if as_of else None
    balance, out = 0, []
    for m in sorted(months, key=lambda m: m["period"]):
        period = m["period"]
        owes = int(owed_by_period.get(period, m["owed_atomic"]))
        given = sum(int(t["amount_atomic"]) for t in m.get("transfers") or [] if t.get("verified"))
        balance = balance + owes - given
        state = ("kept" if balance <= 0 else
                 "carried" if balance < CARRY_UNDER and not quarter_ends(period) else "owed")
        row = {"period": period, "owed_atomic": str(owes), "given_atomic": str(given),
               "balance_atomic": str(max(balance, 0)), "standing": state}
        if today and cause_named and balance > 0:
            month_due = _month_end(period) + timedelta(days=grace_days)
            quarter_due = _quarter_end(period) + timedelta(days=grace_days)
            if (state == "owed" and today > month_due) or today > quarter_due:
                row["late"] = True
        out.append(row)
    # A carried balance whose quarter ended with no later month in the book is owed all the same.
    if out and today and cause_named and int(out[-1]["balance_atomic"]) > 0 \
            and today > _quarter_end(out[-1]["period"]) + timedelta(days=grace_days):
        out[-1]["late"] = True
    return out


def check_standing(body: Dict[str, Any], owed_by_period: Optional[Dict[str, int]] = None) -> List[str]:
    """Where the lab states a month's standing, it must be the one carry-1 gives (as of no date: lateness is the
    verifier's to say, not the lab's)."""
    problems = []
    ours = {row["period"]: row for row in standing(body.get("months") or [], owed_by_period=owed_by_period)}
    for m in body.get("months") or []:
        stated = m.get("standing")
        if stated and stated != ours[m["period"]]["standing"]:
            problems.append(f"pledge {m['period']}: the lab says {stated}, carry-1 gives "
                            f"{ours[m['period']]['standing']}")
    return problems


def late(body: Dict[str, Any], as_of: str, owed_by_period: Optional[Dict[str, int]] = None) -> List[str]:
    """Months the pledge is late on, as of a date, once a cause is named (no recipient, nothing can be late)."""
    if not body.get("recipient"):
        return []
    return [f"pledge {row['period']}: {usd(row['balance_atomic'])} still owed, past the grace of {GRACE_DAYS} days"
            for row in standing(body.get("months") or [], as_of=as_of, cause_named=True,
                                owed_by_period=owed_by_period) if row.get("late")]


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
