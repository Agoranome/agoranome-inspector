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

"""Delivery signs read from the chain, the rule `signs-1`: who pays each seller, and who comes back.

A buyer that pays a seller again, in another session, is a sign the first purchase was delivered. Coinbase's index
counts payers too, but its counts are never published here (its data terms). These counts come from the chain alone,
so anyone can recompute them: every USDC Transfer on Base into a seller's pay-to addresses over the window.

For each host on the newest x402 sheet whose offers ask for USDC on Base, from the pay-to addresses its own
endpoints named on that sheet:

  payments  the transfers into its pay-to addresses in the window
  payers    the addresses they came from
  repeat    a payer that paid in two or more sessions, more than 30 minutes (900 blocks) apart
  sweep     a one-session payer that, within an hour (1,800 blocks) of it, paid 5 or more of the other hosts read:
            a bot paying the catalog once, not a buyer
  self      a payer that is itself one of the host's pay-to addresses
  real      payers less sweeps and self

The lab's own rules (src/revenue/seller/who_pays.py), copied. A pay-to address that more than one host names belongs
to a platform, so its payments can't be told apart and count for none of them ("platform"). An address with more
than BUSY transfers in the window is an exchange's or a busy wallet's and is not read further ("busy"). A host not
reached before the run's time ran out is "not_read". Counts only: no amount, and no payer's address, is published.

Base makes a block every two seconds, so the window and the gaps are in blocks: 30 days is 1,296,000 blocks.

Each week, after the sheet, the book gets a `signs` entry naming the sheet, the window and the hash of the file
(signs/<sheet>.json). The verifier checks the file against its sheet, and with an RPC (verify --chain) counts the
payments and payers of a few hosts again from the chain.
"""

import json
import time
from bisect import bisect_left, bisect_right
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from agoranome_inspector.pledge import BASE_USDC, TRANSFER_TOPIC, _rpc

RULE = "signs-1"
KIND = "agoranome.signs"
FORMAT = 1
NETWORKS = {"eip155:8453", "base"}
BLOCKS_PER_DAY = 43_200
DAYS = 30
GAP_BLOCKS = 900          # 30 minutes between sessions
SWEEP_BLOCKS = 1_800      # an hour either side of a one-session payer's payments
SWEEP_HOSTS = 5
BUSY = 20_000
MAX_HOSTS = 500
BATCH = 100
CHUNK = 10_000
MIN_CHUNK = 500
FINALITY = 10             # blocks left off the head
RECHECK = 3

METHOD = [
    "Every USDC Transfer on Base into a host's pay-to addresses in the window counts; the addresses are those its "
    "own endpoints named on the sheet.",
    "A repeat payer paid in two or more sessions, more than 900 blocks (30 minutes) apart.",
    "A sweep paid in one session and, within 1,800 blocks (an hour), paid 5 or more of the other hosts read.",
    "A self payer is one of the host's own pay-to addresses. Real payers are payers less sweeps and self payers.",
    "An address more than one host names is a platform's and counts for none; an address with more than 20,000 "
    "transfers in the window is not read further. Counts only, never amounts or payers' addresses.",
]


def _is_address(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 42 and text.startswith("0x") and all(c in "0123456789abcdef" for c in text[2:])


def _topic(address: str) -> str:
    return "0x" + "0" * 24 + address.lower()[2:]


def _address(topic: str) -> str:
    return "0x" + str(topic).lower()[-40:]


def targets(sheet: Dict[str, Any], rank: Optional[Dict[str, float]] = None,
            max_hosts: int = MAX_HOSTS) -> Tuple[Dict[str, List[str]], Set[str]]:
    """Each host's pay-to addresses for USDC on Base, as its endpoints named them on the sheet, the busiest
    `max_hosts` first (by `rank`, a private ordering never published, else by rows); and the addresses more than one
    host names (a platform's)."""
    pay_to: Dict[str, Set[str]] = defaultdict(set)
    rows_of: Dict[str, int] = defaultdict(int)
    for r in sheet.get("rows") or []:
        if (r.get("verdict") or {}).get("answer") != "payable":
            continue
        seen = r.get("seen") or {}
        answers = [seen] + ([seen["again"]] if isinstance(seen.get("again"), dict) else [])
        found = {str(o.get("pay_to")).lower() for a in answers for o in a.get("options") or []
                 if isinstance(o, dict) and str(o.get("network") or "").lower() in NETWORKS
                 and str(o.get("asset") or "").lower() == BASE_USDC and _is_address(o.get("pay_to"))}
        if found:
            pay_to[r["host"]].update(found)
            rows_of[r["host"]] += 1
    named: Dict[str, int] = defaultdict(int)
    for addresses in pay_to.values():
        for a in addresses:
            named[a] += 1
    shared = {a for a, n in named.items() if n > 1}
    rank = rank or {}
    order = sorted(pay_to, key=lambda h: (-rank.get(h, 0), -rows_of[h], h))[:max(max_hosts, 0)]
    return {h: sorted(pay_to[h]) for h in sorted(order)}, shared


class ChainReader:
    """USDC Transfers into many addresses at once, over a Base RPC, in block chunks the RPC accepts."""

    def __init__(self, rpc: str, post: Callable[[str, bytes], bytes], chunk: int = CHUNK,
                 pause: float = 0.05, sleep: Callable[[float], None] = time.sleep):
        self.rpc, self.post, self.chunk, self.pause, self.sleep = rpc, post, chunk, pause, sleep

    def head(self) -> int:
        return int(_rpc(self.rpc, "eth_blockNumber", [], self.post), 16)

    def logs(self, addresses: List[str], start: int, end: int) -> List[Dict[str, Any]]:
        out, block = [], start
        while block <= end:
            stop = min(block + self.chunk - 1, end)
            try:
                found = _rpc(self.rpc, "eth_getLogs", [{
                    "address": BASE_USDC, "fromBlock": hex(block), "toBlock": hex(stop),
                    "topics": [TRANSFER_TOPIC, None, [_topic(a) for a in addresses]]}], self.post)
            except ValueError:
                if self.chunk <= MIN_CHUNK:
                    raise
                self.chunk = max(MIN_CHUNK, self.chunk // 2)     # a refused range: half of it, and on
                continue
            out.extend(found or [])
            block = stop + 1
            if self.pause:
                self.sleep(self.pause)
        return out


def read(reader: ChainReader, addresses: List[str], start: int, end: int, *, deadline: Optional[float] = None,
         clock: Callable[[], float] = time.monotonic) -> Tuple[Dict[str, List[Tuple[int, str]]], Set[str], Set[str]]:
    """(block, payer) for every transfer into each address over [start, end]; the addresses read in full; and the
    busy ones. Stops at the deadline: what was read in full still counts."""
    rows: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    done: Set[str] = set()
    busy: Set[str] = set()
    for i in range(0, len(addresses), BATCH):
        group = [a for a in addresses[i:i + BATCH]]
        block = start
        while group and block <= end:
            if deadline is not None and clock() >= deadline:
                return rows, done, busy
            stop = min(block + BLOCKS_PER_DAY - 1, end)
            for log in reader.logs(group, block, stop):
                topics = log.get("topics") or []
                if len(topics) == 3 and str(topics[0]).lower() == TRANSFER_TOPIC:
                    rows[_address(topics[2])].append((int(str(log.get("blockNumber") or "0x0"), 16),
                                                      _address(topics[1])))
            for a in list(group):
                if len(rows[a]) > BUSY:
                    busy.add(a)
                    group.remove(a)
            block = stop + 1
        done.update(group)
    return rows, done, busy


def tally(host_rows: Dict[str, List[Tuple[int, str]]], own: Dict[str, Set[str]]) -> Dict[str, Dict[str, int]]:
    """Each host's counts from its transfers [(block, payer)] (the lab's tally, copied)."""
    paid: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for host, rows in host_rows.items():
        for block, payer in rows:
            paid[payer].append((block, host))
    keys: Dict[str, List[int]] = {}
    for payer, found in paid.items():
        found.sort()
        keys[payer] = [b for b, _ in found]
    out = {}
    for host, rows in host_rows.items():
        blocks: Dict[str, List[int]] = defaultdict(list)
        for block, payer in rows:
            blocks[payer].append(block)
        repeat = sweep = selfpay = 0
        for payer, mine in blocks.items():
            mine.sort()
            if payer in own.get(host, set()):
                selfpay += 1
                continue
            sessions = 1 + sum(1 for a, b in zip(mine, mine[1:]) if b - a > GAP_BLOCKS)
            if sessions > 1:
                repeat += 1
                continue
            lo = bisect_left(keys[payer], mine[0] - SWEEP_BLOCKS)
            hi = bisect_right(keys[payer], mine[-1] + SWEEP_BLOCKS)
            if len({h for _, h in paid[payer][lo:hi]} - {host}) >= SWEEP_HOSTS:
                sweep += 1
        out[host] = {"payments": len(rows), "payers": len(blocks), "repeat_payers": repeat, "sweep_payers": sweep,
                     "self_payers": selfpay, "real_payers": len(blocks) - sweep - selfpay}
    return out


def build(sheet: Dict[str, Any], reader: ChainReader, *, rank: Optional[Dict[str, float]] = None,
          days: int = DAYS, max_hosts: int = MAX_HOSTS, budget_seconds: Optional[float] = None,
          clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """The signs file for one x402 sheet."""
    pay_to, shared = targets(sheet, rank, max_hosts)
    end = reader.head() - FINALITY
    start = end - days * BLOCKS_PER_DAY + 1
    readable = sorted({a for addresses in pay_to.values() for a in addresses} - shared)
    deadline = clock() + budget_seconds if budget_seconds else None
    rows, done, busy = read(reader, readable, start, end, deadline=deadline, clock=clock)
    hosts, counted_rows = [], {}
    states: Dict[str, str] = {}
    for host, addresses in pay_to.items():
        mine = [a for a in addresses if a not in shared]
        state = ("platform" if not mine else "busy" if any(a in busy for a in mine) else
                 "counted" if all(a in done for a in mine) else "not_read")
        states[host] = state
        if state == "counted":
            counted_rows[host] = [row for a in mine for row in rows.get(a, [])]
    counts = tally(counted_rows, {h: set(a) for h, a in pay_to.items()})
    for host, addresses in pay_to.items():
        hosts.append({"host": host, "pay_to": addresses, "state": states[host], **counts.get(host, {})})
    totals = {"hosts": len(hosts), **{s: sum(1 for h in hosts if h["state"] == s)
                                      for s in ("counted", "platform", "busy", "not_read")},
              "with_real_payers": sum(1 for h in hosts if h.get("real_payers")),
              "with_repeat_payers": sum(1 for h in hosts if h.get("repeat_payers"))}
    return {"kind": KIND, "format": FORMAT, "rule": RULE, "sheet": sheet["id"], "network": "eip155:8453",
            "asset": BASE_USDC, "window": {"from_block": start, "to_block": end, "days": days},
            "method": METHOD, "complete": totals["not_read"] == 0, "totals": totals, "hosts": hosts}


def by_host(found: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The counted hosts of a signs file, by host."""
    return {h["host"]: h for h in (found or {}).get("hosts") or [] if h.get("state") == "counted"}


def check_file(found: Dict[str, Any], sheet: Dict[str, Any]) -> List[str]:
    """A signs file against its sheet: the rule, the hosts and their addresses as the sheet named them, and counts
    that hang together."""
    if found.get("rule") != RULE:
        return [f"unknown signs rule {found.get('rule')!r}"]
    if found.get("sheet") != sheet.get("id"):
        return [f"the signs file names sheet {found.get('sheet')}, not {sheet.get('id')}"]
    pay_to, shared = targets(sheet, max_hosts=10 ** 9)
    problems = []
    for h in found.get("hosts") or []:
        if pay_to.get(h.get("host")) != h.get("pay_to"):
            problems.append(f"{h.get('host')}: its pay-to addresses are not those the sheet names")
            continue
        own = [a for a in h["pay_to"] if a not in shared]
        if (h.get("state") == "platform") != (not own):
            problems.append(f"{h['host']}: platform or not, against the sheet")
        if h.get("state") == "counted":
            n = {k: h.get(k) for k in ("payments", "payers", "repeat_payers", "sweep_payers", "self_payers",
                                        "real_payers")}
            if not all(isinstance(v, int) and v >= 0 for v in n.values()) or \
                    n["real_payers"] != n["payers"] - n["sweep_payers"] - n["self_payers"] or \
                    n["repeat_payers"] > n["payers"] or n["payers"] > n["payments"]:
                problems.append(f"{h['host']}: counts that do not hang together")
    hosts = [h.get("host") for h in found.get("hosts") or []]
    if hosts != sorted(set(hosts)):
        problems.append("the hosts are not each listed once, in order")
    return problems


def recheck(found: Dict[str, Any], reader: ChainReader, n: int = RECHECK) -> List[str]:
    """Payments and payers of the first `n` counted hosts, read again from the chain over the same window (these
    two need no other host's transfers)."""
    w = found["window"]
    problems = []
    for h in [h for h in found.get("hosts") or [] if h.get("state") == "counted"][:n]:
        rows: List[Tuple[int, str]] = []
        for log in reader.logs(h["pay_to"], w["from_block"], w["to_block"]):
            topics = log.get("topics") or []
            if len(topics) == 3 and _address(topics[2]) in h["pay_to"]:
                rows.append((int(str(log.get("blockNumber") or "0x0"), 16), _address(topics[1])))
        if (len(rows), len({p for _, p in rows})) != (h["payments"], h["payers"]):
            problems.append(f"{h['host']}: the chain shows {len(rows)} payments from {len({p for _, p in rows})} "
                            f"payers, the file {h['payments']} from {h['payers']}")
    return problems


def to_bytes(found: Dict[str, Any]) -> bytes:
    from agoranome_inspector.canonical import canonical

    return canonical(found) + b"\n"


def load(data: bytes) -> Dict[str, Any]:
    return json.loads(data)
