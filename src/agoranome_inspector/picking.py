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

"""Reading the published pick tables for the fair pick (pick.py), each checked against the open book first.

The book's chain and signatures are checked, then the newest pick table of each market is read and its hash
compared with the book's. Recomputing each table from its sheet is the verifier's work (verify), which anyone can
run on the same site.
"""

import json
from typing import Any, Callable, Dict, List, Optional

from agoranome_inspector.book import check_chain, entries_of, parse
from agoranome_inspector.canonical import sha256_hex
from agoranome_inspector.verify import _safe, http_get, opener

SITE = "https://agoranome.github.io/agoranome-inspector/"
# The same files straight from the branch Pages serves, for when Pages is not answering.
RAW = "https://raw.githubusercontent.com/Agoranome/agoranome-inspector/gh-pages/"


def newest_picks(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The newest pick entry of each market, in book order."""
    newest: Dict[str, Dict[str, Any]] = {}
    for e in entries_of("pick", entries):
        newest[e["body"].get("market")] = e
    return sorted(newest.values(), key=lambda e: e["seq"])


def _read_book(site: str, get: Callable[[str], bytes]):
    try:
        read = opener(site, get)
        return read, parse(read("book.jsonl").decode("utf-8"))
    except Exception:
        if site.rstrip("/") + "/" != SITE:
            raise
        read = opener(RAW, get)
        return read, parse(read("book.jsonl").decode("utf-8"))


def load_tables(site: str, *, pinned_kid: Optional[str] = None,
                get: Callable[[str], bytes] = http_get) -> List[Dict[str, Any]]:
    """The newest pick table of each market, each with its book entry's seq."""
    try:
        read, entries = _read_book(site, get)
    except Exception as e:
        raise ValueError(f"could not read the book at {site} ({type(e).__name__}: {e})")
    chain = check_chain(entries, pinned_kid=pinned_kid)
    if not chain.ok:
        raise ValueError("the book does not verify: " + "; ".join(chain.failures))
    tables = []
    for entry in newest_picks(entries):
        body = entry["body"]
        data = read(_safe(body["file"]))
        if sha256_hex(data) != body.get("sha256"):
            raise ValueError(f"{body['file']} does not match the book's hash")
        tables.append({**json.loads(data), "entry": {"seq": entry["seq"], "hash": entry["hash"]}})
    if not tables:
        raise ValueError("the book holds no pick table yet")
    return tables


def describe(found: Dict[str, Any]) -> str:
    """The pick as plain lines, for a person at a terminal."""
    lines = [f"Fair pick ({found['rule']}) for: {found['job']!r}"
             + (f", at most ${found['budget_usd']} a request" if found.get("budget_usd") else "")]
    if found.get("note"):
        lines.append(found["note"])
    for p in found["picked"]:
        lines.append(f"{p['rank']:>2}. ${p['price_usd']:<10} {p['market']:<5} {p['resource']}")
        lines.append(f"    {p['honest']}" + (f"; {p['delivery']}" if p.get("delivery") else "")
                     + f"; match {p['match']}")
    left = found["left_out"]
    lines.append(f"{found['in_running']} in the running; left out: {left['over_budget']} over the budget, "
                 f"{left['weak_match']} weaker matches, {left['no_match']} no match.")
    lines.append("Sheets: " + ", ".join(f"{t['sheet']}" for t in found["from"]))
    return "\n".join(lines)
