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
  links/<id>.json       operators linked across hosts and markets
  picks/<id>.json       the sheet's pick table: what the fair pick ranks (pick.py)
  pledge.json           the 15% pledge as the lab's ledger states it, from the newest pledge entry
  shelves.json          the shelf report card, from the newest shelf entry
  index.html            the page for people, in agoranome.com's theme: the newest summary, every sheet, how to
                        verify (style.css and mark.svg beside it, from theme.py)

Nothing published holds a secret or the index's demand counts (unless the sheet was built to show them).
"""

import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agoranome_inspector import changes as changes_lib
from agoranome_inspector import links as links_lib
from agoranome_inspector import pick as pick_lib
from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector import theme
from agoranome_inspector.book import Book, entries_of
from agoranome_inspector.canonical import canonical, sha256_hex
from agoranome_inspector.keys import Signer
from agoranome_inspector.sheet import LICENCE

BOOK = "book.jsonl"
HEAD = "head.json"
PLEDGE = "pledge.json"
SHELVES = "shelves.json"
ACCOUNTS = "accounts.json"
DISPUTES = "disputes.json"
GATES = "gates.json"


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


def publish(site_dir: str, sheet: Dict[str, Any], signer: Signer, time: Optional[str] = None,
            words: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """Write the sheet, its table and its change log, and put them into the book. A sheet id is published once.
    With the words each listing had the same day (from the run), the sheet's pick table goes in too."""
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
    if words is not None:
        out["pick"] = publish_pick(site, book, out["sheet"], sheet, words, signer, time=time)
    out["head"] = write_head(site, book)
    write_index(site, book)
    return out


def publish_pick(site: Path, book: Book, sheet_entry: Dict[str, Any], sheet: Dict[str, Any],
                 words: Dict[str, List[str]], signer: Signer, time: Optional[str] = None) -> Dict[str, Any]:
    """The sheet's pick table (pick.py), written to the site and put into the book."""
    found = pick_lib.table(sheet, words)
    pick_file = f"picks/{sheet['id']}.json"
    pick_sha = _write(site / pick_file, canonical(found) + b"\n")
    return book.append(signer, "pick", {
        "rule": found["rule"], "market": found["market"], "sheet": {"seq": sheet_entry["seq"], "id": sheet["id"]},
        "file": pick_file, "sha256": pick_sha, "rows": len(found["rows"]), "left_out": found["left_out"],
    }, time=time)


ANSWER_WORDS = {
    "payable": "gave an offer an agent can pay", "unreadable_offer": "answered 402 with no usable offer",
    "no_payment_asked": "answered without asking for payment", "gone": "gone (404 or 410)",
    "http_4xx": "refused the request", "http_5xx": "failed with a server error", "unreachable": "unreachable",
    "declined": "not asked (not public https)", "not_asked": "not reached in this run", "other": "other",
    "wants_input": "wanted a valid request before quoting a price (not judged)",
}


MARKET_WORDS = {
    "x402": ("x402", "Every listing in Coinbase's x402 Bazaar with 3 or more payers in 30 days"),
    "mpp": ("MPP", "Every paid endpoint in the public MPP catalog at mpp.dev (the catalog states no demand), each "
                   "asked with the example request its own OpenAPI document gives, when it gives one"),
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


def write_pledge(site: Path, book: Book) -> Optional[Dict[str, Any]]:
    """pledge.json: the newest pledge entry's figures, with where it sits in the book."""
    pledges = entries_of("pledge", book.entries())
    if not pledges:
        return None
    entry = pledges[-1]
    data = {"book_entry": {"seq": entry["seq"], "hash": entry["hash"]}, **entry["body"]}
    _write(site / PLEDGE, canonical(data) + b"\n")
    return data


def write_accounts(site: Path, book: Book) -> Optional[Dict[str, Any]]:
    """accounts.json: every statement and every month's close (accounts.py), once the book holds one."""
    from agoranome_inspector import accounts as accounts_lib

    entries = book.entries()
    if not any(x.get("kind") in ("statement", "close") for x in entries):
        return None
    data = accounts_lib.summary(entries)
    _write(site / ACCOUNTS, canonical(data) + b"\n")
    return data


def write_disputes(site: Path, book: Book) -> Optional[Dict[str, Any]]:
    """disputes.json: every seller's dispute with its answer (disputes.py), once the book holds one."""
    from agoranome_inspector import disputes as disputes_lib

    entries = book.entries()
    if not any(x.get("kind") == "dispute" for x in entries):
        return None
    data = disputes_lib.summary(entries)
    _write(site / DISPUTES, canonical(data) + b"\n")
    return data


def write_gates(site: Path, book: Book) -> Optional[Dict[str, Any]]:
    """gates.json: the newest reading of the grand concept's gates, completed from the accounts (gates.py)."""
    from agoranome_inspector import gates as gates_lib

    data = gates_lib.summary(book.entries())
    if data is None:
        return None
    _write(site / GATES, canonical(data) + b"\n")
    return data


def write_shelves(site: Path, book: Book) -> Optional[Dict[str, Any]]:
    """shelves.json: the newest shelf report card, with where it sits in the book."""
    found = entries_of("shelf", book.entries())
    if not found:
        return None
    entry = found[-1]
    data = {"book_entry": {"seq": entry["seq"], "hash": entry["hash"]}, **entry["body"]}
    _write(site / SHELVES, canonical(data) + b"\n")
    return data


def _shelf_section(entries) -> str:
    found = entries_of("shelf", entries)
    if not found:
        return ""
    e = html.escape
    body = found[-1]["body"]
    words = {"open": "Open to read", "rank": "Ranking rule published", "matches": "Listings match the live offer",
             "delivery": "Shows delivery", "dispute": "A buyer can dispute"}
    head = "".join(f"<th>{e(words[q])}</th>" for q in words)
    rows = "".join(
        f"<tr><td>{e(c['name'])}</td><td><b>{e(c['grade'])}</b> ({c['points']}/{c['of']})</td>"
        + "".join(f"<td title=\"{e(str(c['answers'][q].get('says') or ''))}\">{e(c['answers'][q]['answer'])}</td>"
                  for q in words) + "</tr>" for c in body["shelves"])
    return (f"<h2>The shelves</h2><p>Where buying agents find paid endpoints, graded by the published rule "
            f"<code>{e(body['rule'])}</code>: yes is 2 points, partly 1; A at 8 of 10, B at 6, C at 4. Four answers "
            f"are facts from each shelf's own documents, with the source and the day read; whether listings match "
            f"the live offer is measured from the newest sheet. A shelf that finds a fact wrong can point to its "
            f"documents, and the correction goes in the book: <a href=\"{SHELVES}\">the card and its facts</a>.</p>"
            f"<table><tr><th>Shelf</th><th>Grade</th>{head}</tr>{rows}</table>\n")


def _pick_section(entries) -> str:
    newest: Dict[str, Dict[str, Any]] = {}
    for x in entries_of("pick", entries):
        newest[x["body"].get("market")] = x
    if not newest:
        return ""
    e = html.escape
    counts = ", ".join(f"{x['body']['rows']:,} {e(MARKET_WORDS.get(m, (m,))[0])} endpoints"
                       for m, x in sorted(newest.items()))
    files = " · ".join(f"<a href=\"{e(x['body']['file'])}\">{e(x['body']['sheet']['id'])}</a>"
                       for _, x in sorted(newest.items()))
    return (f"<h2>The fair pick</h2><p>For a job and a budget, the endpoints that fit, ranked by the published rule "
            f"<code>{e(pick_lib.RULE)}</code>: those that asked what they list first, then those that promise to "
            f"settle only on delivery, then the lower price. No seller can pay for a place. In the running this "
            f"week: {counts}. The tables it ranks: {files}. Anyone gets the same order:</p>"
            f"<pre>agoranome-inspector pick &lt;this site's URL&gt; \"weather forecast for a city\" --budget 0.01\n"
            f"agoranome-inspector mcp      # the same as MCP tools, fair_pick and seller_row</pre>\n")


def _pledge_section(entries) -> str:
    from agoranome_inspector import pledge as pledge_lib

    pledges = entries_of("pledge", entries)
    if not pledges:
        return ""
    e = html.escape
    body = pledges[-1]["body"]
    t = body["totals"]
    usd = pledge_lib.usd
    cause = (f"to the cause's address <code>{e(body['recipient'])}</code>" if body.get("recipient") else
             "to a cause not named yet; what is owed is kept, shown here and paid once one is named")
    from agoranome_inspector import accounts as accounts_lib

    closed = accounts_lib.owed_by_period(entries)
    standing = {r["period"]: r for r in pledge_lib.standing(body["months"], owed_by_period=closed)}
    words = {"kept": "kept", "carried": "carried (under $1, paid by the quarter's end)", "owed": "owed"}
    rows = "".join(
        f"<tr><td>{e(m['period'])}</td><td>{usd(m['counted_atomic'])}</td>"
        f"<td>{usd(standing[m['period']]['owed_atomic'])}{' (closed)' if m['period'] in closed else ''}</td>"
        f"<td>{usd(m['given_atomic'])}</td><td>{e(words[standing[m['period']]['standing']])}</td><td>"
        + ", ".join(f"<code>{e(x['tx_hash'][:12])}…</code>" for x in m.get("transfers") or []) + "</td></tr>"
        for m in body["months"])
    return (f"<h2>The {int(body['pledge_bps']) / 100:g}% pledge</h2>"
            f"<p>Agoranome pledges {int(body['pledge_bps']) / 100:g}% of what it earns, sent once a month in USDC on "
            f"Base {cause}. As the lab's ledger stated it on {e(body['read_at'])}: {usd(t['counted'])} earned that "
            f"owes the pledge, {usd(t['owed'])} owed, {usd(t['given'])} given, {usd(body['outstanding_atomic'])} "
            f"outstanding. The verifier checks the arithmetic, and with <code>--chain</code> each transfer on Base: "
            f"<a href=\"{PLEDGE}\">the figures</a>. A month that owes under $1 carries over and shows as owed; "
            f"nothing is carried past the end of a quarter (rule <code>{pledge_lib.CARRY_RULE}</code>). A closed month "
            f"owes {int(body['pledge_bps']) / 100:g}% of every source, not only x402: "
            f"<a href=\"{ACCOUNTS}\">the accounts</a>.</p>"
            f"<table><tr><th>Month</th><th>Earned on x402</th><th>Owed</th><th>Given</th><th>Standing</th>"
            f"<th>Transfers</th></tr>{rows}</table>\n")


def _bestbuy_section(entries) -> str:
    found = entries_of("bestbuy", entries)
    if not found:
        return ""
    s = found[-1]["body"]["summary"]
    signs = entries_of("signs", entries)
    signed = ""
    if signs:
        t = signs[-1]["body"]["totals"]
        signed = (f" Delivery signs from the chain this week: {t['counted']:,} x402 sellers counted, "
                  f"{t['with_repeat_payers']:,} with buyers who came back (rule <code>signs-1</code>).")
    return (f"<h2>Best buys</h2><p>One list per kind of job, {s['listings']:,} endpoints in {s['categories']} kinds, "
            f"with the real price and the delivery signs side by side.{signed} "
            f"<a href=\"best-buy/index.html\">The best-buy sheets</a>.</p>\n")


def _disputes_section(entries) -> str:
    from agoranome_inspector import disputes as disputes_lib

    if not any(x.get("kind") == "dispute" for x in entries):
        return ""
    s = disputes_lib.summary(entries)
    return (f"<h2>Disputes</h2><p>A seller can dispute its row, signing with the address the row asks payment to; "
            f"the dispute and the answer both go in the book. So far {s['count']:,} dispute(s): {s['upheld']:,} "
            f"upheld, {s['open']:,} waiting for an answer. <a href=\"{DISPUTES}\">Every dispute and answer</a>. "
            f"To file one: <code>POST https://api.agoranome.com/disputes</code>.</p>\n")


def _gates_section(entries) -> str:
    from agoranome_inspector import gates as gates_lib
    from agoranome_inspector import pledge as pledge_lib

    s = gates_lib.summary(entries)
    if s is None:
        return ""
    e = html.escape
    names = {"outside_use": "Outside use", "data_goods": "Data goods", "earned": "Earned money (the lab's receipts)",
             "ask_test": "Ask test"}
    rows = "".join(f"<tr><td>{names[i]}</td><td>{e(g['status'])}</td><td>{e(g['by'] or '')}</td></tr>"
                   for i, g in s["gates"].items())
    month = s.get("earned_month")
    money = (f" The newest closed month, {e(month['period'])}, earned {pledge_lib.usd(month['earned_atomic'])} from "
             f"every source counted as earned, against a bar of {pledge_lib.usd(month['bar_atomic'])}."
             if month else "")
    return (f"<h2>Gates</h2><p>The plan's stop rules, read from the lab on {e(str(s.get('as_of') or ''))} and "
            f"completed from the accounts. The money gate stands at <strong>{e(s['money'])}</strong>.{money} "
            f"A grant never passes it. <a href=\"{GATES}\">The reading</a>.</p>"
            f"<table><thead><tr><th>Gate</th><th>Status</th><th>By</th></tr></thead><tbody>{rows}</tbody></table>\n")


def _accounts_section(entries) -> str:
    from agoranome_inspector import accounts as accounts_lib
    from agoranome_inspector import pledge as pledge_lib

    data = accounts_lib.summary(entries)
    if not data["statements"] and not data["closes"]:
        return ""
    e = html.escape
    usd = pledge_lib.usd
    rows = "".join(
        f"<tr><td>{e(c['period'])}</td><td>"
        + "; ".join(f"{e(s['source'])}{' from ' + e(s['from']) if s.get('from') else ''} {usd(s['usd_atomic'])}"
                    f"{'' if s['earned'] else ' (not earned)'}" for s in c["sources"])
        + f"</td><td>{usd(c['earned_atomic'])}</td><td>{usd(c['owed_atomic'])}</td></tr>" for c in data["closes"])
    named = []
    if data["licensees"]:
        named.append("licensees: " + ", ".join(e(x) for x in data["licensees"]))
    if data["funders"]:
        named.append("funders: " + ", ".join(e(x) for x in data["funders"]))
    return (f"<h2>The accounts</h2><p>What Agoranome earned, month by month and source by source: receipts on the "
            f"chain, and statements for money that came another way (a merchant's payout, a licence, a grant), each "
            f"with the hash of its document. No sponsor's money is taken. {'; '.join(named) + '. ' if named else ''}"
            f"<a href=\"{ACCOUNTS}\">Every statement and close</a> (rules <code>{accounts_lib.RULE}</code> and "
            f"<code>{accounts_lib.CLOSE_RULE}</code>).</p>"
            + (f"<table><tr><th>Month</th><th>Sources</th><th>Earned</th><th>Owed the cause</th></tr>{rows}</table>\n"
               if rows else ""))


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
    sections += (_pick_section(entries) + _bestbuy_section(entries) + _shelf_section(entries)
                 + _disputes_section(entries) + _pledge_section(entries) + _accounts_section(entries)
                 + _gates_section(entries))
    rows = "".join(
        f"<tr><td>{e(sheet_lib.market_of(x['body']))}</td><td>{e(x['body']['id'])}</td><td>{x['body']['rows']:,}</td>"
        f"<td><a href=\"{e(x['body']['file'])}\">JSON</a> · <a href=\"{e(x['body']['csv']['file'])}\">CSV</a></td>"
        f"<td><code>{e(x['body']['root'] or '')}</code></td></tr>" for x in reversed(sheets))
    body = f"""<p class="eyebrow">Agoranome inspector</p>
<h1>The open sheet</h1>
<p class="lead">Paid endpoints that machines buy from, asked for their offer without paying and judged by a published
rule. Free, under {e(LICENCE)}. Every figure here is signed in the open book and can be checked with one command.</p>
{sections}<h2>Every sheet</h2>
<table><tr><th>Market</th><th>Sheet</th><th>Rows</th><th>Files</th><th>Merkle root</th></tr>{rows}</table>
<h2>Check it yourself</h2>
<pre>pip install "git+https://github.com/Agoranome/agoranome-inspector"
agoranome-inspector verify &lt;this site's URL&gt; --key={e(entries[0]['body']['key']['kid'])}</pre>
<p>The book: <a href="book.jsonl">book.jsonl</a> ({len(entries):,} entries). Newest entry:
<code>{e(str(entries[-1]['seq']))}:{e(entries[-1]['hash'])}</code>. Keep it, and check later that the book still holds
it with <code>--since</code>.</p>"""
    # agoranome.com's theme around the same content (Shariar 2026-11-11: "this should be theme, to match rest of the
    # website"); style.css and mark.svg are written beside the page.
    theme.write_assets(site)
    page = theme.page("Agoranome: the open sheet of machine payment offers", body,
                      best_buys=bool(entries_of("bestbuy", entries)))
    (site / "index.html").write_text(page, encoding="utf-8")


def note(site_dir: str, signer: Signer, text: str, refs: Optional[Dict[str, Any]] = None,
         time: Optional[str] = None) -> Dict[str, Any]:
    """A note in the book: a correction, a seller's dispute and its answer, or a change of method."""
    site = Path(site_dir)
    book = Book(str(site / BOOK))
    entry = book.append(signer, "note", {"text": text, **({"refs": refs} if refs else {})}, time=time)
    write_head(site, book)
    return entry
