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

"""The command line.

For anyone:
  verify SITE [--id ID] [--all] [--key KID] [--since SEQ:HASH] [--recheck N] [--chain RPC] [--json]
  proof SITE --resource URL [--id ID]
  verify-receipt SITE PROOF            a receipt's proof from the lab's ledger (URL or file)

  pick SITE JOB [--budget USD] [--market M]   the fair pick: endpoints for a job, by the published rule pick-1
  mcp [SITE]                           the fair pick and the sheet's rows as MCP tools (stdio)

For the inspector's operator:
  keygen --out FILE                    a new signing key (keep it secret; publish the kid it prints)
  measure --out RUN.json               read the index and ask every listing with real demand
  sheet RUN.json --out SHEET.json      judge the run into a sheet
  publish SITE SHEET.json              put the sheet and its change log into the book
  run SITE --private DIR               measure, sheet and publish in one go
  anchor-lab SITE                      copy the lab's monthly receipt roots and pledge figures into the book
  shelf SITE                           grade the shelves (the Bazaar, AgentCore, MPP, Skyfire) into the book
  note SITE TEXT                       a note in the book (a correction)
  statement SITE --type T ...          a payout, licence, prize, grant or credit in the accounts (accounts-1)
  close SITE [--period YYYY-MM]        close finished months: what each source earned and what the pledge owes
  signs SITE --rpc RPC                 payers and repeat payers of each x402 seller, from the chain (signs-1)
  best-buy SITE                        one list per kind of job, price and delivery signs side by side (best-buy-1)
  disputes SITE                        copy sellers' disputes from the lab into the book
  answer SITE ID --outcome O --reason R   the operator's answer to one dispute
  gates SITE                           the plan's gates from the lab, the money gate completed from the accounts
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

from agoranome_inspector import __version__

DEFAULT_SITE = "https://agoranome.github.io/agoranome-inspector/"


def _key(args) -> "object":
    from agoranome_inspector.keys import Signer

    return Signer.load(getattr(args, "key_file", None))


def _since(text: Optional[str]):
    if not text:
        return None
    seq, _, digest = text.partition(":")
    return {"seq": int(seq), "hash": digest}


def cmd_verify(args) -> int:
    from agoranome_inspector.verify import verify

    report = verify(args.site, args.id, pinned_kid=args.key, since=_since(args.since), every=args.all,
                    recheck_n=args.recheck, chain_rpc=args.chain)
    if args.json:
        print(json.dumps({"ok": report.ok, "checks": report.checks, "warnings": report.warnings,
                          "recheck": report.recheck}, indent=2))
    else:
        print("\n".join(report.lines()))
    return 0 if report.ok and not (args.strict and report.warnings) else 1


def cmd_proof(args) -> int:
    from agoranome_inspector.verify import proof_for

    found = proof_for(args.site, args.resource, args.id)
    print(json.dumps(found, indent=2))
    return 0 if found["verified"] else 1


def cmd_verify_receipt(args) -> int:
    from agoranome_inspector.anchor import check_receipt
    from agoranome_inspector.book import check_chain, entries_of, parse
    from agoranome_inspector.verify import http_get, opener

    entries = parse(opener(args.site)("book.jsonl").decode("utf-8"))
    chain = check_chain(entries)
    if not chain.ok:
        print("FAIL  book: " + "; ".join(chain.failures))
        return 1
    raw = http_get(args.proof) if args.proof.startswith(("https://", "http://")) else Path(args.proof).read_bytes()
    found = check_receipt(json.loads(raw), entries_of("anchor", entries))
    print(json.dumps(found, indent=2))
    return 0 if found["ok"] else 1


def cmd_record(args) -> int:
    """A host's record that travels: its rows on every sheet, with proofs and the signed entries (record.py)."""
    from agoranome_inspector import record

    found = record.build(args.site, args.host)
    text = json.dumps(found, indent=1, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(json.dumps({"host": found["host"], "weeks": len(found["weeks"]), "sheets": found["book"]["sheets"],
                          "rows": sum(len(w["rows"]) for w in found["weeks"]), "out": args.out}))
    else:
        sys.stdout.write(text)
    return 0 if found["weeks"] else 2


def cmd_verify_record(args) -> int:
    from agoranome_inspector import record
    from agoranome_inspector.book import parse
    from agoranome_inspector.verify import http_get, opener

    raw = sys.stdin.buffer.read() if args.file in (None, "-") else Path(args.file).read_bytes()
    found = json.loads(raw)
    problems = record.check(found, pinned_kid=args.key)
    if not problems and args.against:
        problems = record.check_against(found, parse(opener(args.against, http_get)("book.jsonl").decode("utf-8")))
    weeks = found.get("weeks") or []
    if problems:
        for p in problems[:20]:
            print(f"FAIL  {p}")
        print("NOT VERIFIED")
        return 1
    print(f"PASS  {found.get('host')}: {len(weeks)} week(s) of the {found.get('book', {}).get('sheets')} sheets in "
          f"the book when it was made, {sum(len(w.get('rows') or []) for w in weeks)} row(s), each folded into "
          f"its sheet's signed root" + (", and every entry still in the live book" if args.against else ""))
    for w in weeks:
        s = w.get("summary") or {}
        print(f"INFO  {w.get('sheet')}: {s.get('rows')} row(s), {s.get('payable_as_listed')} payable as listed, "
              f"{s.get('payable_not_as_listed')} payable not as listed")
    print("VERIFIED")
    return 0


def cmd_check_delivery(args) -> int:
    """A paid lab answer's receipt is bound to its result: recompute the SHA-256 of the result's RFC 8785 form."""
    from agoranome_inspector.canonical import jcs, sha256_hex

    raw = sys.stdin.buffer.read() if args.file in (None, "-") else Path(args.file).read_bytes()
    body = json.loads(raw)
    stated = ((body.get("receipt") or {}).get("delivery") or {}).get("sha256") if isinstance(body, dict) else None
    if not stated or "result" not in body:
        print("FAIL  the answer has no result, or its receipt names no delivery hash")
        return 1
    found = sha256_hex(jcs(body["result"]))
    ok = found == str(stated).lower()
    print(json.dumps({"ok": ok, "receipt_id": body["receipt"].get("receipt_id"), "stated": stated,
                      "recomputed": found, "amount_atomic": body["receipt"].get("amount_atomic"),
                      "ceiling_atomic": body["receipt"].get("ceiling_atomic")}, indent=2))
    return 0 if ok else 1


def cmd_pick(args) -> int:
    from agoranome_inspector.picking import load_tables, describe
    from agoranome_inspector.pick import rank

    try:
        tables = load_tables(args.site, pinned_kid=args.key)
        found = rank(tables, args.job, args.budget, market=args.market, limit=args.limit)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(json.dumps(found, indent=2) if args.json else describe(found))
    return 0 if found["picked"] else 2


def cmd_mcp(args) -> int:
    from agoranome_inspector.mcp_stdio import serve

    serve(args.site, pinned_kid=args.key)
    return 0


def cmd_keygen(args) -> int:
    from agoranome_inspector.keys import Signer

    signer = Signer.generate()
    out = Path(args.out)
    if out.exists():
        print(f"{out} exists; not overwritten", file=sys.stderr)
        return 1
    out.write_text(signer.pem())
    os.chmod(out, 0o600)
    print(json.dumps({"kid": signer.kid, "public_jwk": signer.jwk}, indent=2))
    return 0


def _settings(args):
    from agoranome_inspector.measure import Settings

    return Settings(concurrency=args.concurrency, per_host=args.per_host, budget_seconds=args.budget,
                    min_payers=args.min_payers)


def cmd_measure(args) -> int:
    from agoranome_inspector.measure import run

    found = run(args.id, settings=_settings(args))
    Path(args.out).write_text(json.dumps(found))
    print(json.dumps({"id": found["id"], **found["probe"], "index_listings": found["index"]["listings"]}))
    return 0


def _sheet_from_run(found: dict, publish_index_counts: bool) -> dict:
    from agoranome_inspector import sheet as sheet_lib

    return sheet_lib.build(found["id"], found["listings"], found["seen"],
                           index=found["index"], probe=found["probe"], publish_index_counts=publish_index_counts)


def cmd_sheet(args) -> int:
    from agoranome_inspector import sheet as sheet_lib

    found = json.loads(Path(args.run).read_text())
    built = _sheet_from_run(found, args.publish_index_counts)
    Path(args.out).write_bytes(sheet_lib.to_bytes(built))
    print(json.dumps(built["summary"]))
    return 0


def cmd_publish(args) -> int:
    from agoranome_inspector.publish import publish

    built = json.loads(Path(args.sheet).read_text())
    out = publish(args.site, built, _key(args))
    print(json.dumps(out["head"]))
    return 0


def cmd_run(args) -> int:
    from agoranome_inspector import sheet as sheet_lib
    from agoranome_inspector.checks import before_signing
    from agoranome_inspector.measure import run
    from agoranome_inspector.publish import note, previous_sheet, publish

    signer = _key(args)   # fail before an hours-long run, not after it
    private = Path(args.private)
    private.mkdir(parents=True, exist_ok=True)
    if args.market == "mpp":
        from agoranome_inspector import mpp

        found = mpp.run(args.id, settings=_settings(args))
        (private / f"run-{found['id']}.json").write_text(json.dumps(found))
        built = mpp.build(found)
    else:
        found = run(args.id, settings=_settings(args))
        (private / f"run-{found['id']}.json").write_text(json.dumps(found))
        built = _sheet_from_run(found, args.publish_index_counts)
    reasons = before_signing(built, previous_sheet(args.site, sheet_lib.market_of(built)))
    if reasons and not args.publish_anyway:
        held = private / f"held-{built['id']}.json"
        held.write_bytes(sheet_lib.to_bytes(built))
        print(json.dumps({"held": reasons, "sheet": built["id"], "summary": built["summary"]}))
        print(f"HELD, not published: {'; '.join(reasons)}. Look at {held} and run again with --publish-anyway "
              "to publish it.", file=sys.stderr)
        return 3
    words = {x["resource"]: x.get("words") or [] for x in found.get("listings") or []}
    out = publish(args.site, built, signer, words=words)
    if reasons:
        note(args.site, signer, "Published past the check before signing, by the operator's choice: "
             + "; ".join(reasons) + ".", refs={"sheet": built["id"]})
    print(json.dumps({"summary": built["summary"], "head": out["head"],
                      "pick_rows": out["pick"]["body"]["rows"] if out.get("pick") else None}))
    return 0


def cmd_anchor_lab(args) -> int:
    from agoranome_inspector.anchor import anchor_body, read_ledger
    from agoranome_inspector.book import Book, utc_now
    from agoranome_inspector.publish import BOOK, write_head

    from agoranome_inspector import pledge
    from agoranome_inspector.book import entries_of
    from agoranome_inspector.publish import write_index, write_pledge

    raw = read_ledger(args.ledger)
    site = Path(args.site)
    book = Book(str(site / BOOK))
    signer = _key(args)
    read_at = utc_now()
    entry = book.append(signer, "anchor", anchor_body(args.ledger, raw, read_at))
    out = {"seq": entry["seq"], "roots": entry["body"]["roots"]}
    # The pledge's figures, once the ledger publishes them, and only when they changed since the last reading.
    body = pledge.pledge_body(args.ledger, raw, read_at)
    if body is not None:
        problems = pledge.check(body)
        if problems:
            print("the lab's pledge figures do not add up, so they are not put in the book: " + "; ".join(problems),
                  file=sys.stderr)
            return 3
        last = entries_of("pledge", book.entries())
        if not last or pledge.figures_digest(last[-1]["body"]) != pledge.figures_digest(body):
            kept = book.append(signer, "pledge", body)
            out["pledge"] = {"seq": kept["seq"], "months": len(body["months"]), "owed": body["totals"]["owed"],
                             "given": body["totals"]["given"]}
        write_pledge(site, book)
        write_index(site, book)
    write_head(site, book)
    print(json.dumps(out))
    return 0


def cmd_reports(args) -> int:
    """Copy buyers' reports from the lab's listing into the book (reports.py). Prints counts only."""
    import urllib.error

    from agoranome_inspector import reports
    from agoranome_inspector.book import Book, utc_now
    from agoranome_inspector.publish import BOOK, write_head

    try:
        raw = reports.read_reports(args.source)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(json.dumps({"unchanged": True, "note": "the lab doesn't list buyers' reports yet"}))
            return 0
        raise
    site = Path(args.site)
    book = Book(str(site / BOOK))
    entries = book.entries()
    body = reports.reports_body(args.source, raw, utc_now(), entries)
    problems = reports.check(body, entries)
    if problems:
        print("the lab's reports are not put in the book: " + "; ".join(problems[:5]), file=sys.stderr)
        return 3
    last = [e for e in entries if e.get("kind") == "reports"]
    if not body["reports"] and body["missing"] == ((last[-1]["body"].get("missing") or []) if last else []):
        print(json.dumps({"unchanged": True, "held": body["held"], "listed": body["listed"]}))
        return 0
    entry = book.append(_key(args), "reports", body)
    write_head(site, book)
    print(json.dumps({"seq": entry["seq"], "new": len(body["reports"]), "held": body["held"],
                      "missing": len(body["missing"]), "refused": body["refused"]}))
    return 0


def cmd_shelf(args) -> int:
    from agoranome_inspector import shelf
    from agoranome_inspector.book import Book, entries_of
    from agoranome_inspector.canonical import digest
    from agoranome_inspector.publish import BOOK, write_head, write_index, write_shelves

    site = Path(args.site)
    book = Book(str(site / BOOK))
    entries = book.entries()
    body = shelf.shelf_body(entries)
    last = entries_of("shelf", entries)
    # A new entry only when a fact or a sheet behind the card changed.
    if not last or digest({k: last[-1]["body"].get(k) for k in ("facts", "sheets")}) != \
            digest({k: body.get(k) for k in ("facts", "sheets")}):
        entry = book.append(_key(args), "shelf", body)
        print(json.dumps({"seq": entry["seq"], "grades": {c["shelf"]: c["grade"] for c in body["shelves"]}}))
    else:
        print(json.dumps({"unchanged": True}))
    write_shelves(site, book)
    write_index(site, book)
    write_head(site, book)
    return 0


def cmd_note(args) -> int:
    from agoranome_inspector.publish import note

    entry = note(args.site, _key(args), args.text)
    print(json.dumps({"seq": entry["seq"], "hash": entry["hash"]}))
    return 0


def cmd_statement(args) -> int:
    """Post one statement into the accounts. The document itself stays with the operator; its hash goes in."""
    import hashlib

    from agoranome_inspector import accounts
    from agoranome_inspector.book import Book
    from agoranome_inspector.publish import BOOK, write_accounts, write_head, write_index

    digest = args.document_sha256
    if args.document:
        digest = hashlib.sha256(Path(args.document).read_bytes()).hexdigest()
    funder_agrees = args.funder_agrees_sha256
    if args.funder_agrees:
        funder_agrees = hashlib.sha256(Path(args.funder_agrees).read_bytes()).hexdigest()
    body = accounts.statement_body(
        kind=args.type, payer=args.payer, period=args.period, amount_usd=args.amount_usd, document_sha256=digest,
        document_url=args.document_url, currency=args.currency, amount=args.amount, tx_hash=args.tx,
        list_price_usd=args.list_price_usd, graded_host=args.graded_host, grant_tests=args.passes_grant_tests,
        funder_agrees_sha256=funder_agrees, note=args.note)
    site = Path(args.site)
    book = Book(str(site / BOOK))
    entry = book.append(_key(args), "statement", body)
    write_accounts(site, book)
    write_index(site, book)
    write_head(site, book)
    print(json.dumps({"seq": entry["seq"], "type": body["type"], "period": body["period"],
                      "pledged": body["pledged"]}))
    return 0


def cmd_close(args) -> int:
    """Close each finished month that has income and no close yet (or the one month named, again)."""
    from agoranome_inspector import accounts
    from agoranome_inspector.book import Book, utc_now
    from agoranome_inspector.publish import BOOK, write_accounts, write_head, write_index

    site = Path(args.site)
    book = Book(str(site / BOOK))
    entries = book.entries()
    periods = [args.period] if args.period else accounts.months_to_close(entries, utc_now())
    if args.period and not accounts.PERIOD.match(args.period):
        raise ValueError("--period must be YYYY-MM")
    if args.period and args.period >= utc_now()[:7]:
        raise ValueError("only a finished month can be closed")
    signer = _key(args) if periods else None
    closed = []
    for period in periods:
        body = accounts.close_body(book.entries(), period)
        entry = book.append(signer, "close", body)
        closed.append({"seq": entry["seq"], "period": period, "owed_atomic": body["owed_atomic"]})
    if closed:
        write_accounts(site, book)
        write_index(site, book)
        write_head(site, book)
    print(json.dumps({"closed": closed} if closed else {"unchanged": True}))
    return 0


def cmd_signs(args) -> int:
    """Delivery signs from the chain for the newest x402 sheet (signs.py). Prints counts only."""
    from agoranome_inspector import pledge, signs
    from agoranome_inspector.book import Book, entries_of
    from agoranome_inspector.publish import BOOK, _write, load_sheet, write_head, write_index

    site = Path(args.site)
    book = Book(str(site / BOOK))
    entries = book.entries()
    sheets = [e for e in entries_of("sheet", entries) if (e["body"].get("market") or "x402") == "x402"]
    if not sheets:
        raise LookupError("the book holds no x402 sheet yet")
    entry = sheets[-1]
    if any((e["body"].get("sheet") or {}).get("id") == entry["body"]["id"] for e in entries_of("signs", entries)):
        print(json.dumps({"unchanged": True, "sheet": entry["body"]["id"]}))
        return 0
    sheet = load_sheet(site, entry)
    rank = {}
    run_file = Path(args.private) / f"run-{sheet['id']}.json" if args.private else None
    if run_file and run_file.exists():     # the index's payer counts: they order the reading, never published
        for x in json.loads(run_file.read_text()).get("listings") or []:
            rank[x.get("host")] = max(rank.get(x.get("host"), 0), float(x.get("payers_30d") or 0))
    reader = signs.ChainReader(args.rpc, pledge.http_post)
    found = signs.build(sheet, reader, rank=rank, days=args.days, max_hosts=args.max_hosts,
                        budget_seconds=args.budget_seconds)
    file = f"signs/{sheet['id']}.json"
    digest = _write(site / file, signs.to_bytes(found))
    kept = book.append(_key(args), "signs", {
        "rule": found["rule"], "market": "x402", "sheet": {"seq": entry["seq"], "id": sheet["id"]}, "file": file,
        "sha256": digest, "window": found["window"], "complete": found["complete"], "totals": found["totals"]})
    write_index(site, book)
    write_head(site, book)
    print(json.dumps({"seq": kept["seq"], "totals": found["totals"], "complete": found["complete"]}))
    return 0


def cmd_bestbuy(args) -> int:
    """Best-buy sheets from the signed pick tables, signs and reports (bestbuy.py). Prints counts only."""
    from agoranome_inspector import bestbuy
    from agoranome_inspector.book import Book, entries_of, utc_now
    from agoranome_inspector.canonical import canonical, sha256_hex
    from agoranome_inspector.publish import BOOK, _write, write_head, write_index

    site = Path(args.site)
    book = Book(str(site / BOOK))
    entries = book.entries()

    def read(entry):
        data = (site / entry["body"]["file"]).read_bytes()
        if sha256_hex(data) != entry["body"]["sha256"]:
            raise RuntimeError(f"{entry['body']['file']} does not match the book")
        return json.loads(data)
    got = bestbuy.inputs(entries, read)
    if got is None:
        print(json.dumps({"unchanged": True, "note": "no pick table yet"}))
        return 0
    found = bestbuy.build(got["tables"], got["signs"], got["reports"], got["sources"])
    data = canonical(found) + b"\n"
    digest = sha256_hex(data)
    last = entries_of("bestbuy", entries)
    if last and last[-1]["body"]["sha256"] == digest:
        print(json.dumps({"unchanged": True}))
        return 0
    file = f"best-buy/{utc_now()[:10]}-{digest[:12]}.json"
    _write(site / file, data)
    entry = book.append(_key(args), "bestbuy", {"rule": found["rule"], "file": file, "sha256": digest,
                                                "sources": found["sources"], "summary": bestbuy.summary(found)})
    (site / "best-buy" / "index.html").write_text(bestbuy.page(found, file), encoding="utf-8")
    write_index(site, book)
    write_head(site, book)
    print(json.dumps({"seq": entry["seq"], **bestbuy.summary(found)}))
    return 0


def _local_tables(site: Path, entries):
    """table_for(sheet_id): the pick table the book signed for that sheet, read from the site, or None."""
    from agoranome_inspector.canonical import sha256_hex

    cache = {}

    def table_for(sheet_id):
        if sheet_id not in cache:
            cache[sheet_id] = None
            pick = next((e for e in reversed(entries) if e["kind"] == "pick"
                         and (e["body"].get("sheet") or {}).get("id") == sheet_id), None)
            if pick is not None:
                data = (site / pick["body"]["file"]).read_bytes()
                if sha256_hex(data) == pick["body"]["sha256"]:
                    cache[sheet_id] = json.loads(data)
        return cache[sheet_id]
    return table_for


def cmd_disputes(args) -> int:
    """Copy sellers' disputes from the lab's listing into the book (disputes.py). Prints counts only."""
    import urllib.error

    from agoranome_inspector import disputes
    from agoranome_inspector.book import Book, utc_now
    from agoranome_inspector.publish import BOOK, write_disputes, write_head, write_index

    try:
        raw = disputes.read_disputes(args.source)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(json.dumps({"unchanged": True, "note": "the lab doesn't list disputes yet"}))
            return 0
        raise
    site = Path(args.site)
    book = Book(str(site / BOOK))
    entries = book.entries()
    body = disputes.disputes_body(args.source, raw, utc_now(), entries, _local_tables(site, entries))
    if not body["disputes"]:
        print(json.dumps({"unchanged": True, "listed": body["listed"], "refused": body["refused"]}))
        return 0
    entry = book.append(_key(args), "dispute", body)
    write_disputes(site, book)
    write_index(site, book)
    write_head(site, book)
    print(json.dumps({"seq": entry["seq"], "new": len(body["disputes"]), "refused": body["refused"]}))
    return 0


def cmd_gates(args) -> int:
    """Read the lab's gates and complete the money gate from the accounts (gates.py). Prints statuses only."""
    import urllib.error

    from agoranome_inspector import gates
    from agoranome_inspector.book import Book, utc_now
    from agoranome_inspector.publish import BOOK, write_gates, write_head, write_index

    try:
        raw = gates.read_gates(args.source)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(json.dumps({"unchanged": True, "note": "the lab doesn't publish its gates yet"}))
            return 0
        raise
    site = Path(args.site)
    book = Book(str(site / BOOK))
    entries = book.entries()
    body = gates.gates_body(args.source, raw, utc_now(), entries)
    if not gates.changed(body, entries):
        print(json.dumps({"unchanged": True, "money": body["money"]}))
        return 0
    entry = book.append(_key(args), "gates", body)
    write_gates(site, book)
    write_index(site, book)
    write_head(site, book)
    print(json.dumps({"seq": entry["seq"], "money": body["money"],
                      "gates": {k: v["status"] for k, v in body["gates"].items()}}))
    return 0


def cmd_answer(args) -> int:
    """The operator's answer to one dispute, in the book beside it."""
    from agoranome_inspector import disputes
    from agoranome_inspector.book import Book
    from agoranome_inspector.publish import BOOK, write_disputes, write_head, write_index

    site = Path(args.site)
    book = Book(str(site / BOOK))
    body = disputes.answer_body(book.entries(), args.id, args.outcome, args.reason, args.correction)
    entry = book.append(_key(args), "answer", body)
    write_disputes(site, book)
    write_index(site, book)
    write_head(site, book)
    print(json.dumps({"seq": entry["seq"], "dispute": args.id, "outcome": args.outcome}))
    return 0


def cmd_weekly_note(args) -> int:
    from agoranome_inspector.assist import weekly_note

    path = weekly_note(args.site)
    print(f"weekly note: {path}" if path else "weekly note: none this week")
    return 0


def cmd_buyer_test(args) -> int:
    """Agoranome's own listings read by a buying model, with the fair pick run on its jobs (buyers.py)."""
    from agoranome_inspector import buyers
    from agoranome_inspector.verify import http_get

    try:
        openapi = json.loads(http_get(args.openapi))
    except Exception as e:  # noqa: BLE001 - the test is skipped; the sheets are unchanged
        print(f"buyer test: the lab's listings were not read ({type(e).__name__}), so none this week")
        return 0
    base = args.openapi.rsplit("/openapi.json", 1)[0]
    try:
        path = buyers.buyer_test(args.site, openapi, base=base)
    except ValueError as e:
        print(f"buyer test: {e}")
        return 2
    if path is None:
        print("buyer test: none this week")
        return 0
    print(f"buyer test: {path} " + json.dumps(json.loads(path.read_text())["counts"], sort_keys=True))
    return 0


def cmd_verdict_study(args) -> int:
    from agoranome_inspector import buyers

    found = buyers.verdict_study(rotations=args.rotations)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"counts": found["counts"], "fisher_one_sided_p": found["fisher_one_sided_p"],
                      "out": args.out}, sort_keys=True))
    answered = sum(c["answered"] for c in found["counts"].values())
    return 0 if answered else 2


def cmd_doctor(args) -> int:
    from agoranome_inspector.assist import doctor_issue, open_issue

    log = Path(args.log).read_text(errors="replace") if args.log and Path(args.log).exists() else ""
    url = open_issue(doctor_issue(log, args.run_url))
    print(f"run doctor: {url or 'issue printed above'}")
    return 0


def cmd_red_team(args) -> int:
    from agoranome_inspector.assist import open_issue, red_team, red_team_issue

    signer = _key(args)      # without the signing key the findings could not be sealed, so nothing is asked
    findings = red_team(args.repo)
    if findings is None:
        print("red-team: no answer this month (no key, the cap, or no usable answer)")
        return 0
    if not findings:
        print("red-team: no findings")
        return 0
    url = open_issue(red_team_issue(findings, signer))
    print(f"red-team: {len(findings)} findings, {url or 'issue printed above'}")
    return 0


def cmd_reveal(args) -> int:
    from agoranome_inspector.assist import unseal

    text = Path(args.file).read_text() if args.file else sys.stdin.read()
    print(unseal(text, _key(args)))
    return 0


def cmd_spend(args) -> int:
    from agoranome_inspector import models

    ledger = models.Ledger(args.ledger or os.environ.get("INSPECTOR_SPEND_LEDGER") or "")
    month = args.month
    print(json.dumps({"month": month or "this month", "spent_usd": round(ledger.spent(month), 4),
                      "cap_usd": models.cap()}))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agoranome-inspector", description="The public inspector of the x402 market.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    v = sub.add_parser("verify", help="check a published sheet against the open book")
    v.add_argument("site", help="the site's URL or a local directory")
    v.add_argument("--id", help="the sheet to check (default: the newest of each market)")
    v.add_argument("--all", action="store_true", help="check every sheet in the book")
    v.add_argument("--key", help="the first signing key's kid, as published elsewhere")
    v.add_argument("--since", help="an entry you kept earlier, as SEQ:HASH, that must still be in the book")
    v.add_argument("--recheck", type=int, default=0, help="ask N rows' endpoints again, unpaid")
    v.add_argument("--chain", metavar="RPC", help="a Base RPC URL: check the pledge's transfers on the chain")
    v.add_argument("--json", action="store_true")
    v.add_argument("--strict", action="store_true", help="fail on a warning too, such as a pledge paid late")
    v.set_defaults(func=cmd_verify)

    pr = sub.add_parser("proof", help="one row of a sheet with its Merkle proof")
    pr.add_argument("site")
    pr.add_argument("--resource", required=True)
    pr.add_argument("--id")
    pr.set_defaults(func=cmd_proof)

    vr = sub.add_parser("verify-receipt", help="check a lab receipt's proof against the roots the book kept")
    vr.add_argument("site")
    vr.add_argument("proof", help="the proof's URL or a file")
    vr.set_defaults(func=cmd_verify_receipt)

    rc = sub.add_parser("record", help="a seller's record that travels: its rows on every sheet, with proofs")
    rc.add_argument("site")
    rc.add_argument("host")
    rc.add_argument("--out", help="write it here (default: standard output)")
    rc.set_defaults(func=cmd_record)

    vrc = sub.add_parser("verify-record", help="check a record from the record alone, with the pinned first key")
    vrc.add_argument("file", nargs="?", help="the record (default: standard input)")
    vrc.add_argument("--key", help="the book's first key id, as published")
    vrc.add_argument("--against", help="also check each entry still stands in this site's live book")
    vrc.set_defaults(func=cmd_verify_record)

    cd = sub.add_parser("check-delivery", help="check a paid lab answer's receipt names the hash of its result")
    cd.add_argument("file", nargs="?", help="the answer's JSON (default: standard input)")
    cd.set_defaults(func=cmd_check_delivery)

    pk = sub.add_parser("pick", help="the fair pick: endpoints for a job, ranked by the published rule pick-1")
    pk.add_argument("site", help="the published site (URL or directory)")
    pk.add_argument("job", help="what the endpoint should do, in words")
    pk.add_argument("--budget", help="the most to pay for one request, in US dollars")
    pk.add_argument("--market", choices=["x402", "mpp"], help="one market only")
    pk.add_argument("--limit", type=int, default=10)
    pk.add_argument("--key", help="the kid the book's first key must have")
    pk.add_argument("--json", action="store_true")
    pk.set_defaults(func=cmd_pick)

    mc = sub.add_parser("mcp", help="serve the fair pick and the sheet's rows as MCP tools on stdin and stdout")
    mc.add_argument("site", nargs="?", default=DEFAULT_SITE, help="the published site (URL or directory)")
    mc.add_argument("--key", help="the kid the book's first key must have")
    mc.set_defaults(func=cmd_mcp)

    k = sub.add_parser("keygen", help="a new Ed25519 signing key")
    k.add_argument("--out", required=True)
    k.set_defaults(func=cmd_keygen)

    def measuring(sp):
        sp.add_argument("--id", help="the sheet's id (default: the market and today's UTC date)")
        sp.add_argument("--concurrency", type=int, default=16)
        sp.add_argument("--per-host", type=int, default=100)
        sp.add_argument("--budget", type=float, default=3 * 3600, help="seconds for the whole run")
        sp.add_argument("--min-payers", type=int, default=3)

    m = sub.add_parser("measure", help="read the index and ask every listing with real demand")
    m.add_argument("--out", required=True)
    measuring(m)
    m.set_defaults(func=cmd_measure)

    s = sub.add_parser("sheet", help="judge a run into a sheet")
    s.add_argument("run")
    s.add_argument("--out", required=True)
    s.add_argument("--publish-index-counts", action="store_true",
                   help="show the index's payer and call counts in the rows (see Coinbase's terms first)")
    s.set_defaults(func=cmd_sheet)

    pu = sub.add_parser("publish", help="put a sheet and its change log into the book")
    pu.add_argument("site")
    pu.add_argument("sheet")
    pu.add_argument("--key-file")
    pu.set_defaults(func=cmd_publish)

    r = sub.add_parser("run", help="measure, sheet and publish")
    r.add_argument("site")
    r.add_argument("--private", required=True, help="where the private run file is kept")
    r.add_argument("--key-file")
    r.add_argument("--publish-index-counts", action="store_true")
    r.add_argument("--publish-anyway", action="store_true",
                   help="publish even when the check before signing would hold the sheet (the book says so)")
    r.add_argument("--market", choices=("x402", "mpp"), default="x402",
                   help="x402 (Coinbase's Bazaar index) or mpp (the MPP catalog at mpp.dev)")
    measuring(r)
    r.set_defaults(func=cmd_run)

    a = sub.add_parser("anchor-lab", help="copy the lab's monthly receipt roots and pledge figures into the book")
    a.add_argument("site")
    a.add_argument("--ledger", default="https://api.agoranome.com/impact/ledger")
    a.add_argument("--key-file")
    a.set_defaults(func=cmd_anchor_lab)

    rp = sub.add_parser("reports", help="copy buyers' reports, each tied to a payment on Base, into the book")
    rp.add_argument("site")
    rp.add_argument("--source", default="https://api.agoranome.com/reports.json")
    rp.add_argument("--key-file")
    rp.set_defaults(func=cmd_reports)

    sh = sub.add_parser("shelf", help="grade the shelves machines shop from, by the rule shelf-1")
    sh.add_argument("site")
    sh.add_argument("--key-file")
    sh.set_defaults(func=cmd_shelf)

    n = sub.add_parser("note", help="a note in the book")
    n.add_argument("site")
    n.add_argument("text")
    n.add_argument("--key-file")
    n.set_defaults(func=cmd_note)

    st = sub.add_parser("statement", help="post a payout, licence, prize, grant or credit into the accounts")
    st.add_argument("site")
    st.add_argument("--type", required=True, choices=("payout", "licence", "prize", "grant", "credit"),
                    help="grant = for named work, paid by milestone; prize = a grant with no strings, or a reward")
    st.add_argument("--from", dest="payer", required=True, help="who paid: the merchant, licensee or funder")
    st.add_argument("--period", required=True, help="YYYY-MM, the month the money arrived")
    st.add_argument("--amount-usd", required=True, help="what reached Agoranome, in US dollars")
    doc = st.add_mutually_exclusive_group(required=True)
    doc.add_argument("--document", help="the statement, licence or award notice (only its hash goes in the book)")
    doc.add_argument("--document-sha256", help="the document's SHA-256, when the file is elsewhere")
    st.add_argument("--document-url", help="where the document is public, if it is")
    st.add_argument("--currency", help="the currency it was paid in, if not dollars (e.g. EUR)")
    st.add_argument("--amount", help="the amount as paid, in that currency")
    st.add_argument("--tx", help="the transaction hash, when it came over a chain")
    st.add_argument("--list-price-usd", help="a licence: the public list price it was sold at")
    st.add_argument("--graded-host", help="the host of a payer the inspector grades, to print beside its row")
    st.add_argument("--passes-grant-tests", action="store_true",
                    help="a grant or prize: the funder passed the five tests (else it is refused)")
    agree = st.add_mutually_exclusive_group()
    agree.add_argument("--funder-agrees", help="a grant for named work: the funder's written agreement that the "
                                               "pledge applies (only its hash goes in the book)")
    agree.add_argument("--funder-agrees-sha256")
    st.add_argument("--note", help="a short note, at most 280 characters")
    st.add_argument("--key-file")
    st.set_defaults(func=cmd_statement)

    cl = sub.add_parser("close", help="close finished months: each source's earnings and what the pledge owes")
    cl.add_argument("site")
    cl.add_argument("--period", help="close this month (again, after a late statement)")
    cl.add_argument("--key-file")
    cl.set_defaults(func=cmd_close)

    sg = sub.add_parser("signs", help="delivery signs from the chain: payers and repeat payers of each x402 seller")
    sg.add_argument("site")
    sg.add_argument("--rpc", required=True, help="a Base RPC URL that answers eth_getLogs")
    sg.add_argument("--private", help="the private run directory (its index counts order the reading only)")
    sg.add_argument("--days", type=int, default=30)
    sg.add_argument("--max-hosts", type=int, default=500)
    sg.add_argument("--budget-seconds", type=float, default=2400)
    sg.add_argument("--key-file")
    sg.set_defaults(func=cmd_signs)

    bb = sub.add_parser("best-buy", help="best-buy sheets: one list per kind of job, price and signs side by side")
    bb.add_argument("site")
    bb.add_argument("--key-file")
    bb.set_defaults(func=cmd_bestbuy)

    dp = sub.add_parser("disputes", help="copy sellers' disputes, each signed by the row's pay-to, into the book")
    dp.add_argument("site")
    dp.add_argument("--source", default="https://api.agoranome.com/disputes.json")
    dp.add_argument("--key-file")
    dp.set_defaults(func=cmd_disputes)

    gt = sub.add_parser("gates", help="the plan's gates from the lab, the money gate completed from the accounts")
    gt.add_argument("site")
    gt.add_argument("--source", default="https://api.agoranome.com/gates.json")
    gt.add_argument("--key-file")
    gt.set_defaults(func=cmd_gates)

    an = sub.add_parser("answer", help="the operator's answer to a seller's dispute, in the book beside it")
    an.add_argument("site")
    an.add_argument("id", help="the dispute's id (d-...)")
    an.add_argument("--outcome", required=True, choices=("upheld", "not_upheld"))
    an.add_argument("--reason", required=True, help="why, in at most 500 characters")
    an.add_argument("--correction", help="an upheld dispute: what the row should say")
    an.add_argument("--key-file")
    an.set_defaults(func=cmd_answer)

    wn = sub.add_parser("weekly-note", help="a model's short note on the newest sheets, numbers checked (notes/)")
    wn.add_argument("site")
    wn.set_defaults(func=cmd_weekly_note)

    bt = sub.add_parser("buyer-test", help="a model reads Agoranome's own listings as a buyer; the fair pick runs "
                                           "on its jobs (buyer-test/)")
    bt.add_argument("site")
    bt.add_argument("--openapi", default="https://api.agoranome.com/openapi.json",
                    help="the lab's /openapi.json (only api.agoranome.com is read)")
    bt.set_defaults(func=cmd_buyer_test)

    vs = sub.add_parser("verdict-study", help="once: does a shown verdict move a buying model? (offers we wrote)")
    vs.add_argument("--out", required=True)
    vs.add_argument("--rotations", type=int, default=3, choices=range(1, 4))
    vs.set_defaults(func=cmd_verdict_study)

    d = sub.add_parser("doctor", help="open an issue on a held or failed weekly run, with a model's reading")
    d.add_argument("--log", help="the run's log")
    d.add_argument("--run-url")
    d.set_defaults(func=cmd_doctor)

    rt = sub.add_parser("red-team", help="a model reads this code for weaknesses; findings sealed in an issue")
    rt.add_argument("--repo", default=".")
    rt.add_argument("--key-file")
    rt.set_defaults(func=cmd_red_team)

    rv = sub.add_parser("reveal", help="read a sealed red-team report with the signing key")
    rv.add_argument("file", nargs="?", help="the issue's text (default: standard input)")
    rv.add_argument("--key-file")
    rv.set_defaults(func=cmd_reveal)

    sp = sub.add_parser("spend", help="the month's model spend against the cap")
    sp.add_argument("--ledger")
    sp.add_argument("--month", help="YYYY-MM (default: this month)")
    sp.set_defaults(func=cmd_spend)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=os.environ.get("INSPECTOR_LOG", "WARNING"))
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (LookupError, RuntimeError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
