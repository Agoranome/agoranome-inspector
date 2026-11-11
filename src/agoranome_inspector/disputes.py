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

"""Sellers' disputes and the inspector's answers, both in the open book.

A seller disputes a row at the lab (POST /disputes on api.agoranome.com): it names the row's resource, the sheet, the
field it disputes and what it says the field should be, as one short token, with an optional https link to its own
evidence, and signs it (EIP-191) with the address the row asks payment to. Only the seller holds that key. The lab
lists them at /disputes.json.

`agoranome-inspector disputes SITE` copies each dispute the book doesn't hold yet into a `dispute` entry, in strict
formats, after checking that the address that signed is one the row on the named sheet's pick table asks payment to.
The signature itself can be checked by anyone with any EIP-191 library (the message is in the entry); the verifier
checks it too when eth_account is installed.

The operator answers each one with `agoranome-inspector answer SITE ID --outcome upheld|not_upheld --reason TEXT`:
an `answer` entry naming the dispute. Upheld means the row was wrong and the next sheet or a correction note puts it
right; not upheld gives the reason, in the operator's words. No model reads a dispute or writes an answer. A dispute
or an answer is never edited or removed, and a dispute can be answered once.
"""

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urlsplit

from agoranome_inspector.canonical import sha256_hex

LAB_DISPUTES = "https://api.agoranome.com/disputes.json"
FIELDS = ("price", "pay_to", "answer", "category", "fair_offer", "signs")
OUTCOMES = ("upheld", "not_upheld")
CLAIM = re.compile(r"^[A-Za-z0-9._:$/-]{1,100}$")
ID = re.compile(r"^d-[0-9a-f]{16}$")
SHEET = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
SIGNATURE = re.compile(r"^0x[0-9a-fA-F]{130}$")
MAX_DISPUTES = 2000
MAX_REASON = 500


def message(resource: str, sheet: str, field: str, claim: str, evidence: Optional[str]) -> str:
    """What the seller signed (the lab's disputes.message)."""
    return (f"Agoranome seller dispute\nResource: {resource}\nSheet: {sheet}\nField: {field}\nClaim: {claim}\n"
            f"Evidence: {evidence or 'none'}")


def strict(d: Any) -> Optional[Dict[str, Any]]:
    """One dispute in the book's formats, or None when any field isn't what the rules allow."""
    if not isinstance(d, dict):
        return None
    resource = str(d.get("resource") or "")
    host = (urlsplit(resource).hostname or "").lower() if resource.startswith("https://") else ""
    evidence = d.get("evidence") or None
    out = {
        "id": str(d.get("id") or ""), "resource": resource, "host": host, "market": d.get("market"),
        "sheet": str(d.get("sheet") or ""), "field": d.get("field"), "claim": str(d.get("claim") or ""),
        "evidence": evidence, "seller": str(d.get("seller") or "").lower(),
        "signature": str(d.get("signature") or ""), "filed_at": str(d.get("filed_at") or "")[:20],
    }
    if not (ID.match(out["id"]) and host and len(resource) <= 2048 and out["market"] in ("x402", "mpp")
            and SHEET.match(out["sheet"]) and out["field"] in FIELDS and CLAIM.match(out["claim"])
            and ADDRESS.match(out["seller"]) and SIGNATURE.match(out["signature"]) and len(out["filed_at"]) == 20):
        return None
    if evidence is not None and (not isinstance(evidence, str) or not evidence.startswith("https://")
                                 or len(evidence) > 500 or any(c.isspace() for c in evidence)):
        return None
    return out


def held(entries: Iterable[Dict[str, Any]]) -> Set[str]:
    return {d["id"] for e in entries if e.get("kind") == "dispute" for d in e["body"].get("disputes") or []}


def answered(entries: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {e["body"]["dispute"]: e for e in entries if e.get("kind") == "answer"}


def _pay_to(row: Dict[str, Any]) -> Optional[str]:
    pay = row.get("pay") or {}
    address = str(pay.get("pay_to") or pay.get("recipient") or "").lower()
    return address if ADDRESS.match(address) else None


def check_seller(d: Dict[str, Any], table: Optional[Dict[str, Any]]) -> Optional[str]:
    """Why a dispute's signer is not the row's seller on its sheet's pick table, or None when it is."""
    if table is None:
        return f"{d['id']}: the book holds no pick table for sheet {d['sheet']}"
    sellers = {_pay_to(r) for r in table.get("rows") or [] if r.get("resource") == d["resource"]} - {None}
    if not sellers:
        return f"{d['id']}: {d['resource']} is not in the running on sheet {d['sheet']}"
    if d["seller"] not in sellers:
        return f"{d['id']}: signed by an address the row does not ask payment to"
    return None


def check_signature(d: Dict[str, Any]) -> Optional[str]:
    """With eth_account installed, the signature recovers to the seller; without it, nothing is said."""
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError:
        return None
    try:
        found = Account.recover_message(encode_defunct(text=message(d["resource"], d["sheet"], d["field"],
                                                                     d["claim"], d["evidence"])),
                                        signature=d["signature"]).lower()
    except Exception:
        found = None
    return None if found == d["seller"] else f"{d['id']}: the signature is not the seller's"


def disputes_body(url: str, raw: bytes, read_at: str, entries: List[Dict[str, Any]],
                  table_for) -> Dict[str, Any]:
    """The disputes the listing shows that the book doesn't hold, each checked against its row's seller."""
    listing = json.loads(raw, parse_float=str)
    shown = listing.get("disputes") if isinstance(listing, dict) else None
    if not isinstance(shown, list):
        raise ValueError("the lab's listing has no disputes list")
    kept = held(entries)
    new: Dict[str, Dict[str, Any]] = {}
    refused = 0
    for d in shown[:MAX_DISPUTES]:
        found = strict(d)
        if found is None or check_seller(found, table_for(found["sheet"])) or check_signature(found):
            refused += 1
            continue
        if found["id"] not in kept:
            new[found["id"]] = found
    return {"source": url, "read_at": read_at, "sha256": sha256_hex(raw), "listed": len(shown), "refused": refused,
            "disputes": sorted(new.values(), key=lambda d: (d["filed_at"], d["id"]))}


def check(body: Dict[str, Any], earlier: Iterable[Dict[str, Any]], table_for) -> List[str]:
    """A dispute entry: strict formats, none held twice, each signed by its row's seller."""
    problems = []
    before = held(earlier)
    for d in body.get("disputes") or []:
        if strict(d) != d:
            problems.append(f"{d.get('id')}: not in the book's formats")
            continue
        if d["id"] in before:
            problems.append(f"{d['id']}: already in the book")
        problems += [p for p in (check_seller(d, table_for(d["sheet"])), check_signature(d)) if p]
    return problems


def answer_body(entries: List[Dict[str, Any]], dispute_id: str, outcome: str, reason: str,
                correction: Optional[str] = None) -> Dict[str, Any]:
    """An answer to one dispute the book holds and has not answered. ValueError otherwise."""
    if dispute_id not in held(entries):
        raise ValueError(f"the book holds no dispute {dispute_id}")
    if dispute_id in answered(entries):
        raise ValueError(f"dispute {dispute_id} is answered already; an answer is never changed")
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome is one of {', '.join(OUTCOMES)}")
    reason = " ".join(str(reason or "").split())
    if not reason or len(reason) > MAX_REASON:
        raise ValueError(f"give the reason, in at most {MAX_REASON} characters")
    body = {"dispute": dispute_id, "outcome": outcome, "reason": reason}
    if correction:
        if outcome != "upheld":
            raise ValueError("a correction goes with an upheld dispute")
        body["correction"] = " ".join(str(correction).split())[:MAX_REASON]
    return body


def summary(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """disputes.json: every dispute with its answer, if any."""
    answers = answered(entries)
    rows = []
    for e in entries:
        if e.get("kind") != "dispute":
            continue
        for d in e["body"].get("disputes") or []:
            a = answers.get(d["id"])
            rows.append({**d, "book_entry": e["seq"], "answer": {"seq": a["seq"], **a["body"]} if a else None})
    return {"kind": "agoranome.disputes", "format": 1, "count": len(rows),
            "open": sum(1 for r in rows if r["answer"] is None),
            "upheld": sum(1 for r in rows if (r["answer"] or {}).get("outcome") == "upheld"), "disputes": rows}


def read_disputes(url: str = LAB_DISPUTES, get=None) -> bytes:
    if get is None:
        from agoranome_inspector.verify import http_get as get
    return get(url)
