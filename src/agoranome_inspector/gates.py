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

"""The grand concept's gates, kept in the open book (`gates` entries, gates.json on the site).

The lab tracks four gates at https://api.agoranome.com/gates.json: one outside sign of use within 60 days of reaching
the shelves, a data good retired under 10 payers at day 60, earned money covering $47.06 a month by day 90 after the
go-ahead, and the ask test. The lab counts only what it sees: its x402 and card receipts. Licence fees, payouts and
prizes are in this book's accounts, so `agoranome-inspector gates SITE` reads the lab's page, keeps each gate's
status and date, and completes the money gate from the newest closed month (close-1): what that month earned from
every source counted as earned (accounts-1), against the bar. A grant is not earned, so it never passes the gate.

An entry is added only when a status or the money figure changed. Counts only: no caller, payer or seller is named,
and nothing of the Bazaar's payer or call counts is read.
"""

import json
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from agoranome_inspector.canonical import sha256_hex

LAB_GATES = "https://api.agoranome.com/gates.json"
GATES_FILE = "gates.json"
IDS = ("outside_use", "data_goods", "earned", "ask_test")
STATUSES = ("waiting", "open", "met", "missed", "keep", "retire", "retire_some", "not_run", "passed", "failed")
BAR_ATOMIC = 47_060_000          # $40 of computing over the 85% left after the 15% pledge
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day(value: Any) -> Optional[str]:
    text = str(value or "")
    if not DAY.match(text):
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def lab_gates(raw: bytes) -> Dict[str, Any]:
    """The lab's page in this book's strict form: each gate's status and date. ValueError when it isn't the page."""
    page = json.loads(raw)
    if not isinstance(page, dict) or page.get("kind") != "agoranome.gates":
        raise ValueError("not the lab's gates page")
    found = {g.get("id"): g for g in page.get("gates") or [] if isinstance(g, dict)}
    if any(i not in found for i in IDS):
        raise ValueError("the lab's gates page lacks a gate")
    out = {}
    for i in IDS:
        status = found[i].get("status")
        if status not in STATUSES:
            raise ValueError(f"gate {i}: status {status!r} is not one this book knows")
        out[i] = {"status": status, "by": _day(found[i].get("by"))}
    return {"as_of": _day(page.get("as_of")), "go_ahead": _day(page.get("go_ahead")), "gates": out}


def earned_month(entries: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The newest closed month's earned money, every source together, against the bar."""
    from agoranome_inspector import accounts

    done = accounts.closes(entries)
    if not done:
        return None
    period = max(done)
    close = done[period]
    earned = int(close["body"]["earned_atomic"])
    return {"period": period, "close_seq": close["seq"], "earned_atomic": str(earned),
            "bar_atomic": str(BAR_ATOMIC), "covers": earned >= BAR_ATOMIC}


def money_status(lab_status: str, month: Optional[Dict[str, Any]]) -> str:
    """The money gate with the book's accounts: met when either the lab's receipts or the closed month cover it."""
    if lab_status == "met" or (month and month["covers"]):
        return "met"
    return lab_status


def gates_body(url: str, raw: bytes, read_at: str, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    lab = lab_gates(raw)
    month = earned_month(entries)
    return {"source": url, "read_at": read_at, "sha256": sha256_hex(raw), **lab, "earned_month": month,
            "money": money_status(lab["gates"]["earned"]["status"], month)}


def _same(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    keep = ("gates", "earned_month", "money", "go_ahead")
    return all(a.get(k) == b.get(k) for k in keep)


def changed(body: Dict[str, Any], entries: Iterable[Dict[str, Any]]) -> bool:
    last = None
    for e in entries:
        if e.get("kind") == "gates":
            last = e
    return last is None or not _same(last["body"], body)


def check(entry: Dict[str, Any], entries: List[Dict[str, Any]]) -> List[str]:
    """A gates entry: strict statuses, and the money figure the entries before it give."""
    body = entry["body"]
    problems = []
    gates = body.get("gates") or {}
    if sorted(gates) != sorted(IDS) or any((g or {}).get("status") not in STATUSES for g in gates.values()):
        problems.append(f"gates entry {entry['seq']}: a gate is missing or has an unknown status")
        return problems
    month = earned_month([e for e in entries if e["seq"] < entry["seq"]])
    if body.get("earned_month") != month:
        problems.append(f"gates entry {entry['seq']}: the closed months before it give another earned figure")
    if body.get("money") != money_status(gates["earned"]["status"], month):
        problems.append(f"gates entry {entry['seq']}: the money gate does not follow from its figures")
    return problems


def summary(entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """gates.json: the newest gates entry, with where it sits in the book."""
    last = None
    for e in entries:
        if e.get("kind") == "gates":
            last = e
    if last is None:
        return None
    return {"kind": "agoranome.gates.book", "format": 1, "book_entry": {"seq": last["seq"], "hash": last["hash"]},
            **last["body"]}


def read_gates(url: str = LAB_GATES, get=None) -> bytes:
    if get is None:
        from agoranome_inspector.verify import http_get as get
    return get(url)
