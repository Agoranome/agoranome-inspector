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

"""The verifier: one command that checks a published sheet against the open book, trusting nothing it is told.

  agoranome-inspector verify https://<site> [--id 2026-11-16] [--key <kid>] [--since <seq>:<hash>]

It checks, in order:
  1. the book: every entry's place, hash and signature, and each key hand-over;
  2. the sheet file: its SHA-256 is the one the book signed;
  3. the rows: their Merkle root and count are the ones the book signed;
  4. the verdicts: every row judged again under the sheet's own rule gives the published verdict;
  5. the summary: counted again from the rows, it matches the sheet and the book;
  6. the table: the CSV is the one the book signed and is rebuilt byte for byte from the sheet;
  7. the change log, when there is one: rebuilt from this sheet and the one before, it matches.

With --recheck N it also asks N rows' endpoints again, unpaid, and says how many still give the same verdict.
That is a spot check of the inspector's own observations, not a pass or fail: the market moves.
"""

import json
import random
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from agoranome_inspector import changes as changes_lib
from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.book import check_chain, entries_of, parse
from agoranome_inspector.canonical import canonical, sha256_hex
from agoranome_inspector.merkle import merkle_proof, verify_proof
from agoranome_inspector.rules import RULES

MAX_BYTES = 256 * 1024 * 1024
SAFE_PATH = re.compile(r"^(sheets|changes|links|picks)/[A-Za-z0-9._-]+\.(json|csv)$")


def http_get(url: str, timeout: float = 60.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Agoranome-inspector-verify/0.1",
                                                   "Accept": "application/json, text/csv, */*"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:   # noqa: S310 (https or a local path only)
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"{url} is larger than {MAX_BYTES} bytes")
    return data


def opener(source: str, get: Callable[[str], bytes] = http_get) -> Callable[[str], bytes]:
    """Read a published file by its path in the site, from a URL or a local directory."""
    if source.startswith(("https://", "http://")):
        base = source.rstrip("/") + "/"
        return lambda rel: get(urljoin(base, rel))
    root = Path(source)
    return lambda rel: (root / rel).read_bytes()


def _safe(rel: str) -> str:
    if not SAFE_PATH.match(rel or ""):
        raise ValueError(f"the book names a file outside the site's sheets and changes: {rel!r}")
    return rel


@dataclass
class Report:
    checks: List[Dict[str, Any]] = field(default_factory=list)
    recheck: Optional[Dict[str, Any]] = None

    def add(self, name: str, ok: bool, detail: str) -> bool:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return ok

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    def lines(self) -> List[str]:
        out = [f"{'PASS' if c['ok'] else 'FAIL'}  {c['check']}: {c['detail']}" for c in self.checks]
        if self.recheck:
            r = self.recheck
            out.append(f"INFO  recheck: {r['same']} of {r['asked']} rows asked again today gave the same verdict"
                       + (f"; differ: {', '.join(r['differ'][:5])}" if r["differ"] else ""))
        out.append("VERIFIED" if self.ok else "NOT VERIFIED")
        return out


def newest_by_market(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The newest sheet entry of each market, in book order."""
    newest: Dict[str, Dict[str, Any]] = {}
    for e in entries_of("sheet", entries):
        newest[sheet_lib.market_of(e["body"])] = e
    return sorted(newest.values(), key=lambda e: e["seq"])


def _sheet_entry(entries: List[Dict[str, Any]], sheet_id: Optional[str]) -> Optional[Dict[str, Any]]:
    sheets = entries_of("sheet", entries)
    if sheet_id is None:
        return sheets[-1] if sheets else None
    found = [e for e in sheets if e["body"].get("id") == sheet_id]
    return found[-1] if found else None


def _load_sheet(read: Callable[[str], bytes], entry: Dict[str, Any], report: Report) -> Optional[Dict[str, Any]]:
    body = entry["body"]
    label = f"sheet {body.get('id')}"
    try:
        data = read(_safe(body["file"]))
    except Exception as e:
        report.add(f"{label} file", False, f"could not read {body.get('file')} ({type(e).__name__}: {e})")
        return None
    digest = sha256_hex(data)
    if not report.add(f"{label} file", digest == body.get("sha256"),
                      f"sha256 {digest}" + ("" if digest == body.get("sha256") else f", book says {body.get('sha256')}")):
        return None
    return json.loads(data)


def check_sheet(read: Callable[[str], bytes], entries: List[Dict[str, Any]], entry: Dict[str, Any],
                report: Report) -> Optional[Dict[str, Any]]:
    body = entry["body"]
    label = f"sheet {body.get('id')}"
    sheet = _load_sheet(read, entry, report)
    if sheet is None:
        return None
    rule = sheet.get("rule")
    if not report.add(f"{label} rule", sheet.get("id") == body.get("id") and rule == body.get("rule")
                      and sheet_lib.market_of(sheet) == sheet_lib.market_of(body)
                      and rule in RULES, f"{sheet_lib.market_of(sheet)} sheet judged under {rule}"
                      + ("" if rule in RULES else " (a rule this verifier does not know: update it)")):
        return None
    rows = sheet.get("rows") or []
    root = sheet_lib.root(sheet)
    report.add(f"{label} rows", root == body.get("root") and len(rows) == body.get("rows"),
               f"{len(rows)} rows, Merkle root {root}")
    wrong = [r.get("resource") for r in rows if RULES[rule](r.get("listed") or [], r.get("seen")) != r.get("verdict")]
    report.add(f"{label} verdicts", not wrong,
               f"all {len(rows)} judged again under {rule}" if not wrong
               else f"{len(wrong)} differ, first: {', '.join(map(str, wrong[:3]))}")
    summary = sheet_lib.summarize(rows)
    report.add(f"{label} summary", summary == sheet.get("summary") == body.get("summary"),
               "counted again from the rows" if summary == sheet.get("summary") == body.get("summary")
               else "the counts do not match the rows")
    csv_ref = body.get("csv") or {}
    if csv_ref:
        try:
            data = read(_safe(csv_ref["file"]))
            same = sha256_hex(data) == csv_ref.get("sha256") and data == sheet_lib.to_csv(sheet).encode("utf-8")
            report.add(f"{label} table", same, "the CSV is the signed one and is rebuilt from the sheet" if same
                       else "the CSV does not match the book or the sheet")
        except Exception as e:
            report.add(f"{label} table", False, f"could not read {csv_ref.get('file')} ({type(e).__name__})")
    for log_entry in entries_of("changes", entries):
        if log_entry["body"].get("to") != body.get("id"):
            continue
        check_changes(read, entries, log_entry, sheet, report)
    return sheet


def check_changes(read: Callable[[str], bytes], entries: List[Dict[str, Any]], log_entry: Dict[str, Any],
                  sheet: Dict[str, Any], report: Report) -> None:
    body = log_entry["body"]
    label = f"changes {body.get('from')} to {body.get('to')}"
    before_entry = _sheet_entry(entries, body.get("from"))
    if before_entry is None:
        report.add(label, False, f"the book holds no sheet {body.get('from')}")
        return
    market = sheet_lib.market_of(sheet)
    after_entry = _sheet_entry(entries, body.get("to"))
    earlier = [e for e in entries_of("sheet", entries)
               if sheet_lib.market_of(e["body"]) == market and after_entry and e["seq"] < after_entry["seq"]]
    if not earlier or earlier[-1]["seq"] != before_entry["seq"]:
        report.add(label, False, f"{body.get('from')} is not the {market} sheet just before {body.get('to')}")
        return
    quiet = Report()
    before = _load_sheet(read, before_entry, quiet)
    if before is None:
        report.add(label, False, f"the sheet before could not be read ({quiet.checks[-1]['detail']})")
        return
    try:
        data = read(_safe(body["file"]))
    except Exception as e:
        report.add(label, False, f"could not read {body.get('file')} ({type(e).__name__})")
        return
    rebuilt = canonical(changes_lib.diff(before, sheet)) + b"\n"
    ok = sha256_hex(data) == body.get("sha256") and data == rebuilt
    counts = changes_lib.diff(before, sheet)["counts"]
    report.add(label, ok and counts == body.get("counts"),
               f"rebuilt from the two sheets: {sum(counts.values())} changes" if ok
               else "the change log does not match the two sheets")


def check_links(read: Callable[[str], bytes], entries: List[Dict[str, Any]], entry: Dict[str, Any],
                report: Report) -> None:
    """A links file is rebuilt from the newest sheet of each market as the book stood when it was written."""
    from agoranome_inspector import links as links_lib

    body = entry["body"]
    label = f"links {body.get('file')}"
    newest: Dict[str, Dict[str, Any]] = {}
    for e in entries_of("sheet", entries):
        if e["seq"] < entry["seq"]:
            newest[sheet_lib.market_of(e["body"])] = e
    expected = [e["body"]["id"] for e in sorted(newest.values(), key=lambda e: e["seq"])]
    if body.get("from") != expected:
        report.add(label, False, f"built from {body.get('from')}, not the newest sheet of each market {expected}")
        return
    quiet = Report()
    sheets = [_load_sheet(read, e, quiet) for e in sorted(newest.values(), key=lambda e: e["seq"])]
    if any(s is None for s in sheets):
        report.add(label, False, "a sheet it was built from could not be read")
        return
    try:
        data = read(_safe(body["file"]))
    except Exception as e:
        report.add(label, False, f"could not read {body.get('file')} ({type(e).__name__})")
        return
    found = links_lib.build(sheets, json.loads(data).get("id", ""))
    ok = (sha256_hex(data) == body.get("sha256") and data == canonical(found) + b"\n"
          and found["counts"] == body.get("counts"))
    report.add(label, ok, f"rebuilt from {', '.join(expected)}: {found['counts']['operators']} operators, "
                          f"{found['counts']['same_host']} hosts in two markets" if ok
               else "the links do not match the sheets")


def check_pick(read: Callable[[str], bytes], entries: List[Dict[str, Any]], entry: Dict[str, Any],
               report: Report) -> None:
    """A pick table is recomputed from the sheet it names, all but the words, which are checked for form."""
    from agoranome_inspector import pick as pick_lib

    body = entry["body"]
    label = f"pick {body.get('file')}"
    ref = body.get("sheet") or {}
    sheet_entry = next((e for e in entries if e["seq"] == ref.get("seq")), None)
    if sheet_entry is None or sheet_entry["kind"] != "sheet" or sheet_entry["body"].get("id") != ref.get("id") \
            or sheet_entry["seq"] > entry["seq"]:
        report.add(label, False, f"names sheet {ref.get('id')} at entry {ref.get('seq')}, which the book lacks")
        return
    sheet = _load_sheet(read, sheet_entry, Report())
    if sheet is None:
        report.add(label, False, f"its sheet {ref.get('id')} could not be read or does not match the book")
        return
    try:
        data = read(_safe(body["file"]))
    except Exception as e:
        report.add(label, False, f"could not read {body.get('file')} ({type(e).__name__})")
        return
    if sha256_hex(data) != body.get("sha256"):
        report.add(label, False, f"sha256 {sha256_hex(data)}, book says {body.get('sha256')}")
        return
    found = json.loads(data)
    problems = pick_lib.check_table(found, sheet)
    if not problems and (len(found["rows"]) != body.get("rows") or found["left_out"] != body.get("left_out")
                         or found["market"] != body.get("market") or data != canonical(found) + b"\n"):
        problems = ["the book's counts do not match the pick table"]
    report.add(label, not problems,
               f"rule {found.get('rule')}: {len(found['rows']):,} rows in the running, recomputed from "
               f"{ref.get('id')}" if not problems else "; ".join(problems))


def check_pledge(entry: Dict[str, Any], report: Report, chain_rpc: Optional[str] = None,
                 post: Optional[Callable[[str, bytes], bytes]] = None) -> None:
    """The pledge's arithmetic in one entry, and with an RPC its transfers on the chain (pledge.py)."""
    from agoranome_inspector import pledge as pledge_lib

    body = entry["body"]
    label = f"pledge {entry['seq']}"
    problems = pledge_lib.check(body)
    if chain_rpc and not problems:
        problems = pledge_lib.check_transfers(body, chain_rpc, post or pledge_lib.http_post)
    t = body.get("totals") or {}
    transfers = sum(len(m.get("transfers") or []) for m in body.get("months") or [])
    report.add(label, not problems,
               f"{len(body.get('months') or [])} month(s): {pledge_lib.usd(t.get('owed', 0))} owed at "
               f"{int(body.get('pledge_bps', 0)) / 100:g}%, {pledge_lib.usd(t.get('given', 0))} given in {transfers} "
               f"transfer(s){', checked on the chain' if chain_rpc else ''}" if not problems else "; ".join(problems))


def recheck(sheet: Dict[str, Any], n: int, ask: Callable[[Dict[str, Any]], Dict[str, Any]],
            rng: Optional[random.Random] = None) -> Dict[str, Any]:
    rng = rng or random.Random()
    rows = [r for r in sheet.get("rows") or [] if r["verdict"]["answer"] not in ("declined", "not_asked")]
    sample = rng.sample(rows, min(n, len(rows)))
    same, differ = 0, []
    for r in sample:
        now = RULES[sheet["rule"]](r.get("listed") or [], ask(r))
        keys = ("answer", "price", "pay_to")
        if all(now.get(k) == r["verdict"].get(k) for k in keys):
            same += 1
        else:
            differ.append(r["resource"])
    return {"asked": len(sample), "same": same, "differ": differ}


def verify(source: str, sheet_id: Optional[str] = None, *, pinned_kid: Optional[str] = None,
           since: Optional[Dict[str, Any]] = None, every: bool = False, recheck_n: int = 0,
           chain_rpc: Optional[str] = None, post: Optional[Callable[[str, bytes], bytes]] = None,
           get: Callable[[str], bytes] = http_get,
           ask: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None) -> Report:
    report = Report()
    read = opener(source, get)
    try:
        entries = parse(read("book.jsonl").decode("utf-8"))
    except Exception as e:
        report.add("book", False, f"could not read book.jsonl ({type(e).__name__}: {e})")
        return report
    chain = check_chain(entries, pinned_kid=pinned_kid, since=since)
    if not report.add("book", chain.ok,
                      (f"{chain.entries} entries, chained and signed; first key {chain.keys[0]['kid']}"
                       + (f", {len(chain.keys) - 1} hand-over(s)" if len(chain.keys) > 1 else "")
                       + f"; head {chain.head['seq']}:{chain.head['hash']}") if chain.ok
                      else "; ".join(chain.failures)):
        return report
    targets = (entries_of("sheet", entries) if every else
               [_sheet_entry(entries, sheet_id)] if sheet_id else newest_by_market(entries))
    if not targets or targets[0] is None:
        report.add("sheet", False, f"the book holds no sheet {sheet_id or ''}".strip())
        return report
    sheet = None
    for entry in targets:
        sheet = check_sheet(read, entries, entry, report)
    link_entries = entries_of("links", entries)
    for entry in (link_entries if every else link_entries[-1:]):
        check_links(read, entries, entry, report)
    picks = entries_of("pick", entries)
    if not every:
        newest_pick: Dict[str, Dict[str, Any]] = {}
        for e in picks:
            newest_pick[e["body"].get("market")] = e
        picks = sorted(newest_pick.values(), key=lambda e: e["seq"])
    for entry in picks:
        check_pick(read, entries, entry, report)
    anchors = entries_of("anchor", entries)
    if anchors:
        months = {m["period"] for a in anchors for m in a["body"].get("roots") or []}
        report.add("anchors", True, f"{len(anchors)} reading(s) of the lab's receipt roots, {len(months)} month(s)")
    pledges = entries_of("pledge", entries)
    for entry in (pledges if every else pledges[-1:]):
        check_pledge(entry, report, chain_rpc, post)
    shelves = entries_of("shelf", entries)
    for entry in (shelves if every else shelves[-1:]):
        from agoranome_inspector import shelf as shelf_lib

        problems = shelf_lib.check(entry["body"], entries)
        report.add(f"shelf {entry['seq']}", not problems,
                   ", ".join(f"{c['name']} {c['grade']}" for c in entry["body"].get("shelves") or [])
                   + f" (rule {entry['body'].get('rule')}, recomputed)" if not problems else "; ".join(problems))
    if recheck_n and sheet is not None and report.ok:
        if ask is None:
            from agoranome_inspector import mpp
            from agoranome_inspector.fetch import SafeFetcher
            from agoranome_inspector.probe import probe

            fetcher = SafeFetcher()
            if sheet_lib.market_of(sheet) == "mpp":
                specs = mpp.SpecReader()
                ask = lambda row: mpp.probe(fetcher, row, example=mpp.example_request(   # noqa: E731
                    specs.spec(row["host"]), row))
            else:
                ask = lambda row: probe(fetcher, row["resource"])   # noqa: E731
        report.recheck = recheck(sheet, recheck_n, ask)
    return report


def proof_for(source: str, resource: str, sheet_id: Optional[str] = None,
              get: Callable[[str], bytes] = http_get) -> Dict[str, Any]:
    """One row of a published sheet with its Merkle proof against the root the book signed."""
    read = opener(source, get)
    entries = parse(read("book.jsonl").decode("utf-8"))
    chain = check_chain(entries)
    if not chain.ok:
        raise RuntimeError("the book does not verify: " + "; ".join(chain.failures))
    # the newest sheet of each market, newest first: an endpoint sold in two markets is found in the newest
    looked = [_sheet_entry(entries, sheet_id)] if sheet_id else newest_by_market(entries)[::-1]
    if not looked or looked[0] is None:
        raise LookupError(f"the book holds no sheet {sheet_id or ''}".strip())
    for entry in looked:
        report = Report()
        sheet = _load_sheet(read, entry, report)
        if sheet is None:
            raise RuntimeError(report.checks[-1]["detail"])
        leaves = sheet_lib.leaves(sheet)
        for row, leaf in zip(sheet["rows"], leaves):
            if row["resource"] == resource:
                proof = merkle_proof(leaves, leaf)
                return {"sheet": sheet["id"], "book_entry": {"seq": entry["seq"], "hash": entry["hash"]},
                        "row": row, "leaf": leaf, "proof": proof, "root": entry["body"]["root"],
                        "verified": verify_proof(leaf, proof, entry["body"]["root"])}
    raise LookupError(f"{resource} is not on sheet {', '.join(e['body']['id'] for e in looked)}")
