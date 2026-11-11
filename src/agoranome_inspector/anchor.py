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

"""Joining the lab's receipts to the open book.

The lab's pledge ledger publishes one Merkle root of settled receipts per month, and a proof for each receipt
(GET /impact/ledger/receipts/{receipt_id}/proof). An anchor entry copies the month roots the ledger shows on
the day it is read into the book, with a hash of the page as read. From then on the lab cannot quietly change
a past month: a receipt's proof must fold into the root the book kept. Reading the ledger changes nothing in
the lab.
"""

import json
from typing import Any, Callable, Dict, List, Optional

from agoranome_inspector.canonical import sha256_hex
from agoranome_inspector.merkle import receipt_leaf, verify_proof

LAB_LEDGER = "https://api.agoranome.com/impact/ledger"


def roots_in(ledger: Dict[str, Any]) -> List[Dict[str, str]]:
    """Each month's root as the lab's ledger shows it, in the schema view (`months`) or the plain one (`roots`,
    `periods`)."""
    found: Dict[str, str] = {}
    for key in ("months", "roots", "periods"):
        for month in ledger.get(key) or []:
            if isinstance(month, dict) and month.get("period") and month.get("merkle_root"):
                found.setdefault(str(month["period"]), str(month["merkle_root"]).lower())
    return [{"period": p, "merkle_root": found[p]} for p in sorted(found)]


def anchor_body(url: str, raw: bytes, read_at: str) -> Dict[str, Any]:
    ledger = json.loads(raw, parse_float=str)   # the book holds no floats: a share of 0.15 is kept as "0.15"
    return {"source": url, "read_at": read_at, "sha256": sha256_hex(raw), "roots": roots_in(ledger),
            "terms": ledger.get("terms") if isinstance(ledger.get("terms"), dict) else None,
            "pledge": ledger.get("pledge") if isinstance(ledger.get("pledge"), str) else None}


def check_receipt(proof: Dict[str, Any], anchors: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fold a receipt's proof from the lab and compare it with the newest root the book kept for its month."""
    entry = proof.get("entry") or {}
    try:
        leaf = receipt_leaf(entry)
    except KeyError as e:
        return {"ok": False, "reason": f"the proof's entry lacks {e}"}
    if proof.get("leaf") and proof["leaf"].lower() != leaf:
        return {"ok": False, "reason": "the proof's leaf is not the hash of its entry"}
    period = proof.get("period")
    kept: Optional[str] = None
    for anchor in anchors:
        for month in anchor["body"].get("roots") or []:
            if month["period"] == period:
                kept = month["merkle_root"]
    if kept is None:
        return {"ok": False, "reason": f"the book holds no root for {period}"}
    if not verify_proof(leaf, list(proof.get("proof") or []), kept):
        return {"ok": False, "reason": f"the proof does not fold into the root the book kept for {period}"}
    return {"ok": True, "period": period, "root": kept, "leaf": leaf}


def read_ledger(url: str = LAB_LEDGER, get: Optional[Callable[[str], bytes]] = None) -> bytes:
    if get is None:
        from agoranome_inspector.verify import http_get as get
    return get(url)
