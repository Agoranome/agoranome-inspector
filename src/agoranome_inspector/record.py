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

"""The record that travels: a seller's history on the sheets, in one file it can carry anywhere.

`agoranome-inspector record SITE HOST` gathers, from every sheet in the open book, the host's rows, each with its
Merkle proof against the root that sheet's book entry signed, and the book entries themselves (the sheets' and the
key entries'), whole and signed. Nothing else is needed to check it: `agoranome-inspector verify-record FILE --key
KID` recomputes each entry's hash, checks its Ed25519 signature by the key in force at its place in the book, and
folds each row into its sheet's root. A row can't be added, dropped from a week shown, or changed without failing.
With `--against SITE` it also checks that each entry still stands at its place in the live book.

What it can't show: weeks the record leaves out. It says how many sheets the book held when it was made
(`book.sheets`), so a reader can ask for the rest. Rows are what the sheet says, verdicts by the published rules;
no grade or opinion is added, and nobody can pay to change one.
"""

from collections import Counter
from typing import Any, Callable, Dict, List, Optional

from agoranome_inspector.book import entry_hash
from agoranome_inspector.keys import verify_signature
from agoranome_inspector.merkle import leaf_hash, merkle_proof, verify_proof

KIND = "agoranome.record"
FORMAT = 1


def _week(entry: Dict[str, Any], sheet: Dict[str, Any], host: str) -> Optional[Dict[str, Any]]:
    from agoranome_inspector import sheet as sheet_lib

    leaves = sheet_lib.leaves(sheet)
    rows = [(r, leaf) for r, leaf in zip(sheet["rows"], leaves) if str(r.get("host") or "").lower() == host]
    if not rows:
        return None
    answers = Counter(r["verdict"].get("answer") for r, _ in rows)
    asked_more = sum(1 for r, _ in rows if r["verdict"].get("answer") == "payable"
                     and r["verdict"].get("matches_listing") is False)
    return {
        "sheet": sheet["id"], "market": sheet_lib.market_of(sheet), "entry": entry,
        "summary": {"rows": len(rows), "answers": dict(sorted(answers.items())),
                    "payable_as_listed": sum(1 for r, _ in rows if r["verdict"].get("answer") == "payable"
                                             and r["verdict"].get("matches_listing") is True),
                    "payable_not_as_listed": asked_more},
        "rows": [{"row": r, "leaf": leaf, "proof": merkle_proof(leaves, leaf)} for r, leaf in rows],
    }


def build(source: str, host: str, *, get: Optional[Callable[[str], bytes]] = None,
          made_at: Optional[str] = None) -> Dict[str, Any]:
    """A host's record from a site (URL or directory) whose book verifies."""
    from agoranome_inspector.book import check_chain, entries_of, parse, utc_now
    from agoranome_inspector.verify import Report, _load_sheet, http_get, opener

    host = host.strip().lower().rstrip(".")
    read = opener(source, get or http_get)
    entries = parse(read("book.jsonl").decode("utf-8"))
    chain = check_chain(entries)
    if not chain.ok:
        raise RuntimeError("the book does not verify: " + "; ".join(chain.failures))
    sheets = entries_of("sheet", entries)
    weeks = []
    for entry in sheets:
        report = Report()
        sheet = _load_sheet(read, entry, report)
        if sheet is None:
            raise RuntimeError(report.checks[-1]["detail"])
        week = _week(entry, sheet, host)
        if week is not None:
            weeks.append(week)
    return {
        "kind": KIND, "format": FORMAT, "host": host, "made_at": made_at or utc_now(),
        "book": {"site": source, "head": chain.head, "sheets": len(sheets)},
        "keys": entries_of("key", entries),
        "weeks": weeks,
        "how": ("Check it with `agoranome-inspector verify-record FILE --key KID`: each entry's hash and Ed25519 "
                "signature by the key in force, and each row's Merkle proof against its sheet's signed root."),
    }


def check(record: Dict[str, Any], pinned_kid: Optional[str] = None) -> List[str]:
    """Everything wrong with a record, from the record alone. Empty means it checks."""
    problems: List[str] = []
    if record.get("kind") != KIND or record.get("format") != FORMAT:
        return [f"not a record of format {FORMAT}"]
    host = str(record.get("host") or "")
    keys = sorted(record.get("keys") or [], key=lambda e: e.get("seq", -1))
    if not keys or keys[0].get("seq") != 0:
        return ["the record lacks the book's first key entry"]
    in_force: List[tuple] = []   # (from seq, jwk)
    signer = (keys[0].get("body") or {}).get("key") or {}
    for entry in keys:
        where = f"key entry {entry.get('seq')}"
        if entry.get("kind") != "key" or entry.get("hash") != entry_hash(entry):
            return [f"{where}: hash does not match its content"]
        sig = entry.get("sig") or {}
        if sig.get("kid") != signer.get("kid") or not verify_signature(signer, bytes.fromhex(entry["hash"][2:]),
                                                                      str(sig.get("value", ""))):
            return [f"{where}: not signed by the key in force"]
        signer = (entry.get("body") or {}).get("key") or {}
        in_force.append((entry["seq"], signer))
    first_kid = in_force[0][1].get("kid")
    if pinned_kid and first_kid != pinned_kid.strip():
        problems.append(f"the book's first key is {first_kid}, not the pinned {pinned_kid}")

    def key_at(seq: int) -> Dict[str, Any]:
        found = in_force[0][1]
        for since, jwk in in_force:
            if since < seq:
                found = jwk
        return found

    for week in record.get("weeks") or []:
        entry = week.get("entry") or {}
        where = f"sheet {week.get('sheet')}"
        try:
            if entry.get("kind") != "sheet" or entry.get("hash") != entry_hash(entry):
                problems.append(f"{where}: its book entry's hash does not match its content")
                continue
        except (KeyError, TypeError):
            problems.append(f"{where}: its book entry is malformed")
            continue
        key = key_at(int(entry["seq"]))
        sig = entry.get("sig") or {}
        if sig.get("kid") != key.get("kid") or not verify_signature(key, bytes.fromhex(entry["hash"][2:]),
                                                                    str(sig.get("value", ""))):
            problems.append(f"{where}: its book entry is not signed by the key in force")
            continue
        root = (entry.get("body") or {}).get("root")
        if (entry.get("body") or {}).get("id") != week.get("sheet"):
            problems.append(f"{where}: the entry names sheet {(entry.get('body') or {}).get('id')}")
        for item in week.get("rows") or []:
            row = item.get("row") or {}
            if str(row.get("host") or "").lower() != host:
                problems.append(f"{where}: a row of another host, {row.get('host')}")
            elif leaf_hash(row) != item.get("leaf") or not verify_proof(item["leaf"], list(item.get("proof") or []),
                                                                         root):
                problems.append(f"{where}: row {row.get('resource')} does not fold into the signed root")
    return problems


def check_against(record: Dict[str, Any], entries: List[Dict[str, Any]]) -> List[str]:
    """Each entry the record carries still stands, unchanged, at its place in the live book."""
    problems = []
    carried = list(record.get("keys") or []) + [w.get("entry") or {} for w in record.get("weeks") or []]
    for entry in carried:
        seq = entry.get("seq")
        if not isinstance(seq, int) or seq >= len(entries) or entries[seq].get("hash") != entry.get("hash"):
            problems.append(f"entry {seq} is not in the live book as the record carries it")
    return problems
