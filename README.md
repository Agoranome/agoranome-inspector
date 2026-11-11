# Agoranome inspector

The public inspector of the x402 market. It asks every paid endpoint with real demand for its offer, without
paying, the way a buyer agent's first call does. It publishes who asks the listed price and pays the listed
address, and it proves every figure in an open book that anyone can check with one command.

Agoranome: fair markets for machines. We build the tools that help AI agents find, judge and trust the services
they pay for, and we pledge 15% of what we earn to a public cause.

This is phase 1 of the plan, "Prove": the sheet, the change log, the open book and its verifier. Nothing here is
sold. The tools are free, and the published sheets are under CC BY 4.0.

One book holds the sheets of several markets. x402 is the first. MPP (the Machine Payments Protocol) and Skyfire
are next: each will get its own sheet and rule beside x402's, in the same book.

## Check a sheet in one command

```sh
pip install "git+https://github.com/shariar-k/agoranome1"
agoranome-inspector verify <site URL or directory> --key=<the first key's kid>
```

To try it now, on a demo site built from a small fake market (every host is under `example.*`):

```sh
agoranome-inspector verify examples/demo-site --all
```

The verifier trusts nothing it is told. It checks, in order:

1. **The book.** Every entry's place, hash and Ed25519 signature, and every hand-over to a new key. With
   `--key=<kid>` the first key must be the one Agoranome publishes elsewhere. With `--since=<seq>:<hash>`, an
   entry you kept earlier must still be in the book, unchanged.
2. **The sheet file.** Its SHA-256 is the one the book signed.
3. **The rows.** Their Merkle root and count are the ones the book signed.
4. **The verdicts.** Every row is judged again under the sheet's own rule and must give the published verdict.
5. **The summary.** Counted again from the rows, it must match the sheet and the book.
6. **The table.** The CSV is the one the book signed and is rebuilt byte for byte from the sheet.
7. **The change log.** Rebuilt from this sheet and the one before, it must match.

`--recheck N` also asks N rows' endpoints again, unpaid, and reports how many still give the same verdict. That
is a spot check of the inspector's own observations, not a pass or fail, because the market moves.

A seller can take its own row with its Merkle proof against the signed root:

```sh
agoranome-inspector proof <site> --resource https://seller.example/api/search
```

## The sheet

One row for each listing in Coinbase's x402 Bazaar index with 3 or more unique payers in 30 days. Each row holds
what the listing states (`listed`), what the endpoint answered (`seen`) and the verdict. The verdict is a pure
function of the other two, so anyone can judge a row again.

### The rule, `sheet-1`

- **Who is on the sheet.** Every listing in the index with 3 or more unique payers in 30 days on the day of the
  run. The index is the list of where to look. Every verdict comes from the seller's own endpoint.
- **How each listing is asked.** An unpaid GET, then an empty JSON POST if the GET did not answer 402, from a
  public address, following no redirect. A listing that gives no payable offer is asked once more a few seconds
  later, and the second answer is kept. A listing whose offer differs from its listing in a way that would count
  against the seller (a higher price, a missing option, another pay-to address) is also asked once more, and both
  answers are kept. Nothing is ever paid.
- **answer.** `payable` when the endpoint answered 402 with at least one payment option naming a network, an
  asset, an amount and a pay-to address (the x402 v2 `PAYMENT-REQUIRED` header or the v1 body).
  `unreadable_offer` for a 402 without one, `no_payment_asked` for a 2xx, `gone` for 404 or 410, `http_4xx` and
  `http_5xx` for other errors, `unreachable` when no HTTP answer came, `declined` when the URL is not public
  https (so it was not asked), `not_asked` when the run reached its per-host cap or time budget first, and
  `other` for anything else.
- **Comparing one listed option.** Its candidates are the live options on the same network, asset and scheme
  (on the same network and asset, any scheme, when none has the same scheme). Its price is `as_listed` when a
  candidate asks exactly the listed amount, `below_listed` when the cheapest asks less, `above_listed` when every
  candidate asks more. Its pay-to is `as_listed` when a candidate pays the listed address, `different` when none
  does.
- **price of the row.** `listed_option_missing` when no listed option has a candidate, `not_listed` when the
  listing states no usable price, else `above_listed` when any compared option is above, else `below_listed`
  when any is below, else `as_listed`.
- **pay_to of the row.** `different` when any compared option is different, else `as_listed`.
- **Confirmation.** When the endpoint was asked twice, a price or pay-to that the two answers do not both give
  is `varies`, and it is not held against the seller.
- **matches_listing.** `true` when the price is `as_listed` or `below_listed` and the pay-to is `as_listed`.
  `false` when the price is `above_listed` or `listed_option_missing`, or the pay-to is `different`. `null`
  otherwise. A `false` says the live offer differs from the listing, which can also mean the listing is out of
  date. It is not a finding of bad faith.
- **differs.** Up to 8 listed options that differ, each with its listed and live amount and address, so a seller
  can see exactly what was compared.
- **Comparing.** Networks as CAIP-2 ids (x402 v1 names are mapped, and a reference longer than 32 characters is
  cut to 32), EVM addresses in lower case, other addresses as written, amounts as whole atomic units.

A rule never changes once a sheet is published under it. A new rule gets a new name, and each sheet names the
rule it was judged by, so an old sheet always verifies under its own rule.

### What the sheet does not publish

Coinbase's developer terms limit sharing data from its tools without written permission. So a published row
carries the seller's own statements and answers, and not the index's payer and call counts. The counts are used
only to choose who is on the sheet, and they stay in the operator's private run file. `sheet
--publish-index-counts` puts them in the rows, and should only be used once Coinbase has said yes in writing.

## The change log

What changed between two sheets, computed from the two sheets alone: `price_cut`, `price_raised`,
`listed_price_changed`, `pay_to_changed`, `went_dark`, `came_back`, `verdict_changed`, `joined` and `left`.
Free and public. The lab sold this as a $1 watch.

## The open book

A JSON Lines file, `book.jsonl`, one entry a line, that only grows:

```json
{"seq":1,"prev":"0x…","time":"2026-11-16T07:00:00Z","kind":"sheet","body":{…},"hash":"0x…","sig":{"kid":"…","alg":"EdDSA","value":"…"}}
```

- `hash` = SHA-256 of the canonical JSON of `{seq, prev, time, kind, body}`. Canonical means keys sorted, no
  whitespace, UTF-8 and no floating-point numbers (every amount is an integer or a decimal string), which matches
  RFC 8785 for the ASCII keys used here.
- `prev` is the hash of the entry before (64 zeros for the first). `sig` is Ed25519 over the 32 bytes of `hash`.
- Entry 0 is a `key` entry naming the signing key, signed by it. A later `key` entry, signed by the key in
  force, hands over to a new key. A key's `kid` is its RFC 7638 thumbprint.
- Kinds: `key`; `sheet` (the file, its SHA-256, the Merkle root of its rows, the count and the summary); `changes`;
  `anchor` (the lab's monthly receipt roots as read on a day); `note` (a correction, a dispute and its answer, a
  change of method). Nothing is edited or removed. A correction is a new entry.

The Merkle tree is the lab's pledge ledger construction, so one verifier proves a sheet row and a lab receipt:

```
leaf = sha256(0x00 || canonical_json(row))        (the lab hashes {receipt_id, payer, amount_atomic, tx_hash})
node = sha256(0x01 || min(a, b) || max(a, b))
leaves sorted; an odd node is promoted unchanged
```

`agoranome-inspector anchor-lab <site>` copies the lab's monthly receipt roots from its public ledger into the
book. From then on a receipt's proof from the lab must fold into the root the book kept:
`agoranome-inspector verify-receipt <site> <proof URL or file>`.

## The published site

Plain files that any static host can serve: `book.jsonl`, `head.json`, `sheets/<id>.json`, `sheets/<id>.csv`,
`changes/<id>.json` and `index.html`. A sheet's id names its market and day (`x402-2026-11-16`). Each change log
compares a sheet with the sheet just before it in the same market, and the verifier checks that it does. With no
`--id`, `verify` checks the newest sheet of each market.

## Running the inspector

```sh
agoranome-inspector keygen --out inspector-key.pem        # keep it secret; publish the kid it prints
export INSPECTOR_SIGNING_KEY="$(cat inspector-key.pem)"   # or pass --key-file
agoranome-inspector run site/ --private private/          # read the index, ask, judge, publish
agoranome-inspector anchor-lab site/                      # optional: join the lab's receipt roots
```

`run` is polite by default: one request at a time to any host, half a second between a host's listings, at most
100 listings of one host (busiest first), 16 hosts at once and a three-hour budget. It needs no model and no paid
service.

### The weekly run

The workflow `Weekly sheet` (`.github/workflows/weekly.yml`, running `scripts/weekly.sh`) runs every Monday at
06:17 UTC and can be started by hand from the Actions tab. It takes the published site from the `gh-pages` branch,
runs the inspector into it, verifies the whole site with the one command, and only then commits it back to
`gh-pages`, which GitHub Pages serves. The git history of `gh-pages` is a second record of every week.

It needs, once, in the repository's settings:

1. **Secrets and variables, Actions, secret `INSPECTOR_SIGNING_KEY`**: the PEM text of the book's signing key, made
   with `agoranome-inspector keygen --out inspector-key.pem`. Keep the file somewhere safe and offline. Until the
   secret is set, the workflow measures and publishes nothing.
2. **Secrets and variables, Actions, variable `INSPECTOR_FIRST_KID`** (optional): the kid `keygen` printed. The run
   then refuses to publish a book whose first key is any other.
3. **Pages**: source "Deploy from a branch", branch `gh-pages`, folder `/ (root)`. The branch exists after the first
   run. The site is then at `https://shariar-k.github.io/agoranome1/`.

The private run file, with the index's payer and call counts, is written outside the site and is discarded with
the runner. GitHub turns off a schedule in a public repository after 60 days without activity; if it ever does,
turn it on again in the Actions tab.

## Where the code came from

Lifted from the lab (`shariar-k/AEAx`) and copied, not imported, so nothing in the lab changes:

| Here | From the lab |
|------|--------------|
| `bazaar.py` | `src/revenue/insights/sources.py` and `analysis.py` (the index reader and the category rules) |
| `fetch.py` | `src/revenue/seller/fetch.py` (the safe fetcher) |
| `probe.py` | `src/revenue/seller/lint.py` (`probe`, `read_offer`) |
| `merkle.py` | `src/revenue/machine/impact.py` (the ledger's Merkle tree) |
| `networks.py` | `src/revenue/seller/lint.py` and `sources.py` (network names, USDC assets) |

## Tests

```sh
pip install -e ".[dev]"
pytest
```

The tests run offline against a small fake market.

## Licence

Code: Apache 2.0 (`LICENSE`). Published sheets, change logs and the book: CC BY 4.0.
