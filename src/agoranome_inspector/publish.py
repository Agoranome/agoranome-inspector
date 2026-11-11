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
  index.html            a plain page for people: the newest summary, every sheet, how to verify

Nothing published holds a secret or the index's demand counts (unless the sheet was built to show them).
"""

import html
import json
from pathlib import Path
from typing import Any, Dict, Optional

from agoranome_inspector import changes as changes_lib
from agoranome_inspector import links as links_lib
from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.book import Book, entries_of
from agoranome_inspector.canonical import canonical, sha256_hex
from agoranome_inspector.keys import Signer
from agoranome_inspector.sheet import LICENCE

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


def previous_sheet(site_dir: str, market: str) -> Optional[Dict[str, Any]]:
    """The last sheet of a market the site's book holds, read and checked against the book; None if there is none."""
    site = Path(site_dir)
    if not (site / BOOK).exists():
        return None
    same = [e for e in entries_of("sheet", Book(str(site / BOOK)).entries())
            if sheet_lib.market_of(e["body"]) == market]
    return load_sheet(site, same[-1]) if same else None


def publish(site_dir: str, sheet: Dict[str, Any], signer: Signer, time: Optional[str] = None) -> Dict[str, Any]:
    """Write the sheet, its table and its change log, and put them into the book. A sheet id is published once."""
    site = Path(site_dir)
    book = Book(str(site / BOOK))
    if not book.entries():
        book.open(signer, time=time)
    sheets = entries_of("sheet", book.entries())
    market = sheet_lib.market_of(sheet)
    if any(e["body"]["id"] == sheet["id"] for e in sheets):
        raise RuntimeError(f"sheet {sheet['id']} is already in the book; publish a correction under a new id")
    sheet_file = f"sheets/{sheet['id']}.json"
    csv_file = f"sheets/{sheet['id']}.csv"
    sheet_sha = _write(site / sheet_file, sheet_lib.to_bytes(sheet))
    csv_sha = _write(site / csv_file, sheet_lib.to_csv(sheet).encode("utf-8"))
    entry = book.append(signer, "sheet", {
        "id": sheet["id"],
        "market": market,
        "rule": sheet["rule"],
        "file": sheet_file,
        "sha256": sheet_sha,
        "root": sheet_lib.root(sheet),
        "rows": len(sheet["rows"]),
        "summary": sheet["summary"],
        "csv": {"file": csv_file, "sha256": csv_sha},
    }, time=time)
    out = {"sheet": entry}
    same_market = [e for e in sheets if sheet_lib.market_of(e["body"]) == market]
    if same_market:
        before = load_sheet(site, same_market[-1])
        log = changes_lib.diff(before, sheet)
        log_file = f"changes/{sheet['id']}.json"
        log_sha = _write(site / log_file, canonical(log) + b"\n")
        out["changes"] = book.append(signer, "changes", {
            "market": market, "from": log["from"], "to": log["to"], "file": log_file, "sha256": log_sha, "counts": log["counts"],
        }, time=time)
    newest: Dict[str, Dict[str, Any]] = {}
    for e in entries_of("sheet", book.entries()):
        newest[sheet_lib.market_of(e["body"])] = e
    sheets_now = [sheet if e["body"]["id"] == sheet["id"] else load_sheet(site, e)
                  for e in sorted(newest.values(), key=lambda e: e["seq"])]
    found = links_lib.build(sheets_now, sheet["id"])
    links_file = f"links/{sheet['id']}.json"
    links_sha = _write(site / links_file, canonical(found) + b"\n")
    out["links"] = book.append(signer, "links", {
        "from": found["from"], "file": links_file, "sha256": links_sha, "counts": found["counts"],
    }, time=time)
    out["head"] = write_head(site, book)
    write_index(site, book)
    return out


ANSWER_WORDS = {
    "payable": "gave an offer an agent can pay", "unreadable_offer": "answered 402 with no usable offer",
    "no_payment_asked": "answered without asking for payment", "gone": "gone (404 or 410)",
    "http_4xx": "refused the request", "http_5xx": "failed with a server error", "unreachable": "unreachable",
    "declined": "not asked (not public https)", "not_asked": "not reached in this run", "other": "other",
}


MARKET_WORDS = {
    "x402": ("x402", "Every listing in Coinbase's x402 Bazaar with 3 or more payers in 30 days"),
    "mpp": ("MPP", "Every paid endpoint in the public MPP catalog at mpp.dev (the catalog states no demand)"),
}


def _market_section(body: Dict[str, Any]) -> str:
    e = html.escape
    s = body["summary"]
    name, who = MARKET_WORDS.get(sheet_lib.market_of(body), (sheet_lib.market_of(body), "Every listing"))
    answers = "".join(f"<li>{n:,} {e(ANSWER_WORDS.get(k, k))}</li>" for k, n in sorted(
        s.get("answer", {}).items(), key=lambda kv: -kv[1]))
    payable = s.get("answer", {}).get("payable", 0)
    price = s.get("price", {})
    pay_to = s.get("pay_to", {})
    if sheet_lib.market_of(body) == "mpp":
        detail = f"""<p>Of the {payable:,} payable challenges, {price.get('as_listed', 0) + price.get('below_listed', 0):,}
asked no more than the catalog's price and {price.get('above_listed', 0):,} asked more;
{price.get('not_listed', 0):,} are priced by the request (dynamic) and not judged on price;
{price.get('varies', 0):,} varied between two asks and are not held against anyone. The catalog names no recipient,
so the recipient each challenge names is recorded, not judged.</p>
"""
    else:
        detail = f"""<p>Of the {payable:,} payable offers, {price.get('as_listed', 0) + price.get('below_listed', 0):,} asked no more than
their listed price and {price.get('above_listed', 0):,} asked more; {pay_to.get('different', 0):,} named a pay-to
address other than the listed one; {price.get('varies', 0) + pay_to.get('varies', 0):,} verdicts varied between two
asks and are not held against anyone. A difference from the listing can mean the listing is out of date.
{s.get('fair_offer', 0):,} carried a Fair Offer block.</p>
"""
    return f"""<h2>{e(name)}: sheet {e(body['id'])}</h2>
<p>{e(who)}, asked without paying (twice when an answer differs from the listing) and judged by the published rule
<code>{e(body['rule'])}</code>. {s.get("rows", 0):,} listings from {s.get("hosts", 0):,} sellers. What they answered:</p>
<ul>{answers}</ul>
{detail}"""


def write_index(site: Path, book: Book) -> None:
    """The page a person lands on. Every figure on it is in a sheet's book entry."""
    entries = book.entries()
    sheets = entries_of("sheet", entries)
    if not sheets:
        return
    e = html.escape
    newest: Dict[str, Dict[str, Any]] = {}
    for x in sheets:
        newest[sheet_lib.market_of(x["body"])] = x
    sections = "".join(_market_section(x["body"]) for x in sorted(newest.values(), key=lambda x: -x["seq"]))
    link_entries = entries_of("links", entries)
    if link_entries:
        c = link_entries[-1]["body"]["counts"]
        sections += (f"<h2>Operators</h2><p>{c['linked_hosts']:,} hosts are linked into {c['operators']:,} operators "
                     f"because their offers ask payment to the same address; {c['same_host']:,} hosts sell in more "
                     f"than one market; {c['platform_addresses']:,} addresses that more than "
                     f"{links_lib.PLATFORM_HOSTS} hosts share are a platform's and link nobody. A link is a fact "
                     f"beside the rows, never a verdict: <a href=\"{e(link_entries[-1]['body']['file'])}\">the "
                     f"links and their evidence</a>.</p>\n")
    rows = "".join(
        f"<tr><td>{e(sheet_lib.market_of(x['body']))}</td><td>{e(x['body']['id'])}</td><td>{x['body']['rows']:,}</td>"
        f"<td><a href=\"{e(x['body']['file'])}\">JSON</a> · <a href=\"{e(x['body']['csv']['file'])}\">CSV</a></td>"
        f"<td><code>{e(x['body']['root'] or '')}</code></td></tr>" for x in reversed(sheets))
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agoranome: the open sheet of machine payment offers</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:52rem;margin:2rem auto;padding:0 1rem;color:#1a1a1a}}
table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:.3rem .5rem;border-bottom:1px solid #ddd}}
code{{font-size:.8em;word-break:break-all}}pre{{background:#f4f4f4;padding:.75rem;overflow-x:auto}}</style></head>
<body>
<h1>The open sheet</h1>
<p>Paid endpoints that machines buy from, asked for their offer without paying and judged by a published rule. Free,
under {e(LICENCE)}. Every figure here is signed in the open book and can be checked with one command.</p>
{sections}<h2>Every sheet</h2>
<table><tr><th>Market</th><th>Sheet</th><th>Rows</th><th>Files</th><th>Merkle root</th></tr>{rows}</table>
<h2>Check it yourself</h2>
<pre>pip install "git+https://github.com/shariar-k/agoranome1"
agoranome-inspector verify &lt;this site's URL&gt; --key={e(entries[0]['body']['key']['kid'])}</pre>
<p>The book: <a href="book.jsonl">book.jsonl</a> ({len(entries):,} entries). Newest entry:
<code>{e(str(entries[-1]['seq']))}:{e(entries[-1]['hash'])}</code>. Keep it, and check later that the book still holds
it with <code>--since</code>.</p>
</body></html>
"""
    (site / "index.html").write_text(page, encoding="utf-8")


def note(site_dir: str, signer: Signer, text: str, refs: Optional[Dict[str, Any]] = None,
         time: Optional[str] = None) -> Dict[str, Any]:
    """A note in the book: a correction, a seller's dispute and its answer, or a change of method."""
    site = Path(site_dir)
    book = Book(str(site / BOOK))
    entry = book.append(signer, "note", {"text": text, **({"refs": refs} if refs else {})}, time=time)
    write_head(site, book)
    return entry
