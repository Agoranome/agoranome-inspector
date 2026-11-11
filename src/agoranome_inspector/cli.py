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
  verify SITE [--id ID] [--all] [--key KID] [--since SEQ:HASH] [--recheck N] [--json]
  proof SITE --resource URL [--id ID]
  verify-receipt SITE PROOF            a receipt's proof from the lab's ledger (URL or file)

For the inspector's operator:
  keygen --out FILE                    a new signing key (keep it secret; publish the kid it prints)
  measure --out RUN.json               read the index and ask every listing with real demand
  sheet RUN.json --out SHEET.json      judge the run into a sheet
  publish SITE SHEET.json              put the sheet and its change log into the book
  run SITE --private DIR               measure, sheet and publish in one go
  anchor-lab SITE                      copy the lab's monthly receipt roots into the book
  note SITE TEXT                       a note in the book (a correction, a dispute and its answer)
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

from agoranome_inspector import __version__


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
                    recheck_n=args.recheck)
    if args.json:
        print(json.dumps({"ok": report.ok, "checks": report.checks, "recheck": report.recheck}, indent=2))
    else:
        print("\n".join(report.lines()))
    return 0 if report.ok else 1


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
    from agoranome_inspector.measure import run
    from agoranome_inspector.publish import publish

    signer = _key(args)   # fail before an hours-long run, not after it
    private = Path(args.private)
    private.mkdir(parents=True, exist_ok=True)
    found = run(args.id, settings=_settings(args))
    (private / f"run-{found['id']}.json").write_text(json.dumps(found))
    built = _sheet_from_run(found, args.publish_index_counts)
    out = publish(args.site, built, signer)
    print(json.dumps({"summary": built["summary"], "head": out["head"]}))
    return 0


def cmd_anchor_lab(args) -> int:
    from agoranome_inspector.anchor import anchor_body, read_ledger
    from agoranome_inspector.book import Book, utc_now
    from agoranome_inspector.publish import BOOK, write_head

    raw = read_ledger(args.ledger)
    book = Book(str(Path(args.site) / BOOK))
    entry = book.append(_key(args), "anchor", anchor_body(args.ledger, raw, utc_now()))
    write_head(Path(args.site), book)
    print(json.dumps({"seq": entry["seq"], "roots": entry["body"]["roots"]}))
    return 0


def cmd_note(args) -> int:
    from agoranome_inspector.publish import note

    entry = note(args.site, _key(args), args.text)
    print(json.dumps({"seq": entry["seq"], "hash": entry["hash"]}))
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
    v.add_argument("--json", action="store_true")
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

    k = sub.add_parser("keygen", help="a new Ed25519 signing key")
    k.add_argument("--out", required=True)
    k.set_defaults(func=cmd_keygen)

    def measuring(sp):
        sp.add_argument("--id", help="the sheet's id (default: x402- and today's UTC date)")
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
    measuring(r)
    r.set_defaults(func=cmd_run)

    a = sub.add_parser("anchor-lab", help="copy the lab's monthly receipt roots into the book")
    a.add_argument("site")
    a.add_argument("--ledger", default="https://api.agoranome.com/impact/ledger")
    a.add_argument("--key-file")
    a.set_defaults(func=cmd_anchor_lab)

    n = sub.add_parser("note", help="a note in the book")
    n.add_argument("site")
    n.add_argument("text")
    n.add_argument("--key-file")
    n.set_defaults(func=cmd_note)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=os.environ.get("INSPECTOR_LOG", "WARNING"))
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (LookupError, RuntimeError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
