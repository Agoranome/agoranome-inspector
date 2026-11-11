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

"""Agoranome's own accounts in the open book: every payout, licence, grant and credit, and each month's close.

Money that arrives on a chain is proven by the lab's receipts (the `anchor` and `pledge` entries). Money that
arrives any other way, such as a merchant's payout for the record, a platform's licence fee or a grant paid through
a bank, can only be posted as a statement. A `statement` entry posts one such sum: what it is, who paid it, the month
it arrived in, what reached Agoranome in US dollars, and the hash of the document behind it (the payout statement,
the licence, the award notice). The book names every licensee and every funder, and what each paid.

How the 15% pledge applies, the rule `accounts-1` (the concept's table, "How the pledge applies to each source"):

  payout     the merchant's payout for the record or a seat     earned    pledged on what was received
  licence    a platform's licence fee, at the public price      earned    pledged on what was received
  prize      a grant with no strings, a prize, a reward        earned    pledged
  grant      a grant for named work, paid by milestone          not earned, so not pledged, unless the funder
                                                                agreed in writing (the agreement's hash is posted)
  credit     a credit in kind, such as cloud credits            not earned, not pledged, listed

A grant or a prize is posted only when the funder passed the five tests ("passed" is the operator's word, kept in the
entry): a programme with public rules others can apply to; no say over a figure, a grade or the method; work whose
results stay open; the amount, terms and each payment in the book; and the funder graded like everyone else. A
licence names the public list price it was sold at: no licence is sold off the price list. A funder or licensee that
the inspector grades is named with its host, so the grant can be printed beside its row.

A `close` entry closes one month: on the first working day of the next month (the month-close workflow, and the
weekly run as a back-stop), the book states what was earned from each source: the lab's x402 receipts (as the
newest `pledge` entry read them) and every statement of the month. What the month owes the cause is each source's
15%, rounded up, added together. The pledge's standing (pledge.py, carry-1) then runs on the close's total. The
verifier recomputes every close from the entries before it.

Who may give, and whether a grant carries the pledge, are rulings the concept left to Shariar. The table above is
the concept's proposal, and it is a rule with a name, so a change is a new rule and never a quiet edit.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional

from agoranome_inspector.pledge import DEFAULT_BPS, owed

RULE = "accounts-1"
CLOSE_RULE = "close-1"
TYPES = ("payout", "licence", "prize", "grant", "credit")
EARNED = {"payout": True, "licence": True, "prize": True, "grant": False, "credit": False}
NEED_TESTS = ("prize", "grant")
PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TX = re.compile(r"^0x[0-9a-f]{64}$")
HOST = re.compile(r"^[a-z0-9.-]{1,253}$")
CURRENCY = re.compile(r"^[A-Z]{3,5}$")
MAX_NAME = 120


def _usd_atomic(value: Any) -> Optional[int]:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if amount < 0 or amount != amount.quantize(Decimal("0.000001")):
        return None
    return int(amount * 1_000_000)


def pledged(kind: str, funder_agrees: bool) -> bool:
    """Whether a statement of this type owes the pledge, under accounts-1."""
    return EARNED.get(kind, False) or (kind == "grant" and funder_agrees)


def statement_body(*, kind: str, payer: str, period: str, amount_usd: Any, document_sha256: str,
                   document_url: Optional[str] = None, currency: Optional[str] = None,
                   amount: Optional[str] = None, tx_hash: Optional[str] = None, list_price_usd: Optional[str] = None,
                   graded_host: Optional[str] = None, grant_tests: bool = False,
                   funder_agrees_sha256: Optional[str] = None, note: Optional[str] = None) -> Dict[str, Any]:
    """One statement's body, or ValueError naming what is wrong. Strict formats, so the book holds no free text but
    the payer's name and a short note the operator writes."""
    if kind not in TYPES:
        raise ValueError(f"type must be one of {', '.join(TYPES)}")
    payer = " ".join(str(payer or "").split())
    if not payer or len(payer) > MAX_NAME:
        raise ValueError(f"name who paid, in at most {MAX_NAME} characters")
    if not PERIOD.match(period or ""):
        raise ValueError("period must be YYYY-MM, the month the money arrived")
    usd_atomic = _usd_atomic(amount_usd)
    if usd_atomic is None:
        raise ValueError("amount_usd must be what reached Agoranome in US dollars, at most six decimals")
    document_sha256 = str(document_sha256 or "").lower().removeprefix("0x")
    if not HEX64.match(document_sha256):
        raise ValueError("document_sha256 must be the SHA-256 of the statement, licence or notice")
    if kind in NEED_TESTS and not grant_tests:
        raise ValueError("a grant or a prize is posted only when the funder passed the five tests; money that "
                         "fails one is refused")
    if kind == "licence" and _usd_atomic(list_price_usd) is None:
        raise ValueError("a licence names the public list price it was sold at")
    if funder_agrees_sha256 is not None:
        funder_agrees_sha256 = funder_agrees_sha256.lower().removeprefix("0x")
        if kind != "grant" or not HEX64.match(funder_agrees_sha256):
            raise ValueError("funder_agrees_sha256 is for a grant for named work: the hash of the funder's written "
                             "agreement that the pledge applies")
    body: Dict[str, Any] = {
        "rule": RULE, "type": kind, "from": payer, "period": period, "usd_atomic": str(usd_atomic),
        "earned": EARNED[kind], "pledged": pledged(kind, funder_agrees_sha256 is not None),
        "document": {"sha256": document_sha256},
    }
    if document_url:
        if not str(document_url).startswith("https://"):
            raise ValueError("document_url must be https")
        body["document"]["url"] = str(document_url)[:500]
    if currency or amount:
        if not CURRENCY.match(currency or "") or _usd_atomic(amount) is None:
            raise ValueError("give both currency (e.g. EUR) and the amount as paid in it")
        body["paid"] = {"currency": currency, "amount": str(Decimal(str(amount)))}
    if tx_hash:
        if not TX.match(str(tx_hash).lower()):
            raise ValueError("tx_hash must be a transaction hash, when the money came over a chain")
        body["tx_hash"] = str(tx_hash).lower()
    if kind == "licence":
        body["list_price_usd"] = str(Decimal(str(list_price_usd)))
    if kind in NEED_TESTS:
        body["grant_tests"] = "passed"
    if funder_agrees_sha256:
        body["funder_agrees_sha256"] = funder_agrees_sha256
    if graded_host:
        host = str(graded_host).lower().strip()
        if not HOST.match(host):
            raise ValueError("graded_host must be a host name")
        body["graded_host"] = host
    if note:
        body["note"] = " ".join(str(note).split())[:280]
    return body


def check_statement(body: Dict[str, Any]) -> List[str]:
    """A statement read back from the book: built again from its own fields, it must come out the same."""
    try:
        again = statement_body(
            kind=body.get("type"), payer=body.get("from"), period=body.get("period"),
            amount_usd=Decimal(int(body.get("usd_atomic"))) / 1_000_000,
            document_sha256=(body.get("document") or {}).get("sha256"),
            document_url=(body.get("document") or {}).get("url"),
            currency=(body.get("paid") or {}).get("currency"), amount=(body.get("paid") or {}).get("amount"),
            tx_hash=body.get("tx_hash"), list_price_usd=body.get("list_price_usd"),
            graded_host=body.get("graded_host"), grant_tests=body.get("grant_tests") == "passed",
            funder_agrees_sha256=body.get("funder_agrees_sha256"), note=body.get("note"))
    except (ValueError, TypeError) as e:
        return [f"statement: {e}"]
    if body.get("rule") != RULE:
        return [f"statement: rule {body.get('rule')!r}, this verifier knows {RULE}"]
    return [] if again == body else ["statement: its earned or pledged flags do not follow from its type (accounts-1)"]


def _pledge_month(entries: Iterable[Dict[str, Any]], period: str):
    """The newest pledge entry and its figures for a month, or (None, None)."""
    found = (None, None)
    for e in entries:
        if e.get("kind") != "pledge":
            continue
        for m in e["body"].get("months") or []:
            if m.get("period") == period:
                found = (e, m)
    return found


def close_body(entries: List[Dict[str, Any]], period: str) -> Dict[str, Any]:
    """The close of one month from the entries in the book: each source, what it earned, and what it owes."""
    pledge_entry, month = _pledge_month(entries, period)
    bps = int(pledge_entry["body"].get("pledge_bps") or DEFAULT_BPS) if pledge_entry else DEFAULT_BPS
    sources: List[Dict[str, Any]] = []
    if month is not None:
        sources.append({"source": "x402", "earned": True, "pledged": True,
                        "usd_atomic": month["counted_atomic"], "owed_atomic": month["owed_atomic"],
                        "receipts": month.get("receipts", 0), "merkle_root": month.get("merkle_root"),
                        "pledge_seq": pledge_entry["seq"]})
    for e in entries:
        if e.get("kind") == "statement" and e["body"].get("period") == period:
            b = e["body"]
            sources.append({"source": b["type"], "from": b["from"], "seq": e["seq"], "earned": b["earned"],
                            "pledged": b["pledged"], "usd_atomic": b["usd_atomic"],
                            "owed_atomic": str(owed(int(b["usd_atomic"]), bps) if b["pledged"] else 0)})
    return {
        "rule": CLOSE_RULE, "period": period, "pledge_bps": bps, "sources": sources,
        "earned_atomic": str(sum(int(s["usd_atomic"]) for s in sources if s["earned"])),
        "outside_atomic": str(sum(int(s["usd_atomic"]) for s in sources if not s["earned"])),
        "owed_atomic": str(sum(int(s["owed_atomic"]) for s in sources)),
    }


def check_close(entry: Dict[str, Any], entries: List[Dict[str, Any]]) -> List[str]:
    """A close must be the one close_body gives from the entries before it."""
    body = entry["body"]
    if body.get("rule") != CLOSE_RULE:
        return [f"close {body.get('period')}: rule {body.get('rule')!r}, this verifier knows {CLOSE_RULE}"]
    again = close_body([e for e in entries if e["seq"] < entry["seq"]], str(body.get("period")))
    if again != body:
        return [f"close {body.get('period')}: the entries before it give a different close "
                f"(owed {again['owed_atomic']}, the entry says {body.get('owed_atomic')})"]
    return []


def closes(entries: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The newest close of each month."""
    out: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        if e.get("kind") == "close":
            out[e["body"]["period"]] = e
    return out


def owed_by_period(entries: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """What each closed month owes the cause, every source together (for pledge.standing)."""
    return {period: int(e["body"]["owed_atomic"]) for period, e in closes(entries).items()}


def months_to_close(entries: List[Dict[str, Any]], today: str) -> List[str]:
    """Finished months with income (receipts in a pledge entry, or a statement) and no close yet, oldest first.
    A month can be closed again later only by hand (a late statement): `close --period` does that."""
    done = closes(entries)
    this_month = today[:7]
    periods = set()
    for e in entries:
        if e.get("kind") == "pledge":
            periods.update(m["period"] for m in e["body"].get("months") or [])
        elif e.get("kind") == "statement":
            periods.add(e["body"]["period"])
    return sorted(p for p in periods if p < this_month and p not in done)


def summary(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The accounts page: every statement, every close, and the totals by source (published as accounts.json)."""
    statements = [{"seq": e["seq"], "time": e.get("time"), **e["body"]} for e in entries
                  if e.get("kind") == "statement"]
    month_closes = [{"seq": e["seq"], "time": e.get("time"), **e["body"]} for e in closes(entries).values()]
    by_source: Dict[str, int] = {}
    for c in month_closes:
        for s in c["sources"]:
            by_source[s["source"]] = by_source.get(s["source"], 0) + int(s["usd_atomic"])
    return {
        "rule": RULE, "close_rule": CLOSE_RULE,
        "statements": statements,
        "closes": sorted(month_closes, key=lambda c: c["period"]),
        "totals_by_source_atomic": {k: str(v) for k, v in sorted(by_source.items())},
        "licensees": sorted({s["from"] for s in statements if s["type"] == "licence"}),
        "funders": sorted({s["from"] for s in statements if s["type"] in ("grant", "prize")}),
    }
