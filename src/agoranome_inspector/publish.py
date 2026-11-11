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

"""Publishing: write a sheet and its change log as plain files and put both into the open book.

The published site is a directory any static host can serve:

  book.jsonl            the open book
  head.json             the newest entry's seq, hash and time, for anyone who wants to keep it
  sheets/<id>.json      a sheet, canonical JSON
  sheets/<id>.csv       the same rows as a table
  changes/<id>.json     what changed since the sheet before

Nothing published holds a secret or the index's demand counts (unless the sheet was built to show them).
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from agoranome_inspector import changes as changes_lib
from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.book import Book, entries_of
from agoranome_inspector.canonical import canonical, sha256_hex
from agoranome_inspector.keys import Signer

BOOK = "book.jsonl"
HEAD = "head.json"


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_hex(data)


def write_head(site: Path, book: Book) -> Dict[str, Any]:
    last = book.entries()[-1]
    head = {"seq": last["seq"], "hash": last["hash"], "time": last["time"], "kid": last["sig"]["kid"]}
    (site / HEAD).write_text(json.dumps(head, indent=2) + "\n", encoding="utf-8")
    return head


def load_sheet(site: Path, entry: Dict[str, Any]) -> Dict[str, Any]:
    """A sheet the book already holds, read from the site after its hash is checked against the book."""
    data = (site / entry["body"]["file"]).read_bytes()
    if sha256_hex(data) != entry["body"]["sha256"]:
        raise RuntimeError(f"{entry['body']['file']} on disk does not match the book")
    return json.loads(data)


def publish(site_dir: str, sheet: Dict[str, Any], signer: Signer, time: Optional[str] = None) -> Dict[str, Any]:
    """Write the sheet, its table and its change log, and put them into the book. A sheet id is published once."""
    site = Path(site_dir)
    book = Book(str(site / BOOK))
    if not book.entries():
        book.open(signer, time=time)
    sheets = entries_of("sheet", book.entries())
    if any(e["body"]["id"] == sheet["id"] for e in sheets):
        raise RuntimeError(f"sheet {sheet['id']} is already in the book; publish a correction under a new id")
    sheet_file = f"sheets/{sheet['id']}.json"
    csv_file = f"sheets/{sheet['id']}.csv"
    sheet_sha = _write(site / sheet_file, sheet_lib.to_bytes(sheet))
    csv_sha = _write(site / csv_file, sheet_lib.to_csv(sheet).encode("utf-8"))
    entry = book.append(signer, "sheet", {
        "id": sheet["id"],
        "rule": sheet["rule"],
        "file": sheet_file,
        "sha256": sheet_sha,
        "root": sheet_lib.root(sheet),
        "rows": len(sheet["rows"]),
        "summary": sheet["summary"],
        "csv": {"file": csv_file, "sha256": csv_sha},
    }, time=time)
    out = {"sheet": entry}
    if sheets:
        before = load_sheet(site, sheets[-1])
        log = changes_lib.diff(before, sheet)
        log_file = f"changes/{sheet['id']}.json"
        log_sha = _write(site / log_file, canonical(log) + b"\n")
        out["changes"] = book.append(signer, "changes", {
            "from": log["from"], "to": log["to"], "file": log_file, "sha256": log_sha, "counts": log["counts"],
        }, time=time)
    out["head"] = write_head(site, book)
    return out


def note(site_dir: str, signer: Signer, text: str, refs: Optional[Dict[str, Any]] = None,
         time: Optional[str] = None) -> Dict[str, Any]:
    """A note in the book: a correction, a seller's dispute and its answer, or a change of method."""
    site = Path(site_dir)
    book = Book(str(site / BOOK))
    entry = book.append(signer, "note", {"text": text, **({"refs": refs} if refs else {})}, time=time)
    write_head(site, book)
    return entry
