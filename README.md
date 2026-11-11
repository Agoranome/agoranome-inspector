# Agoranome inspector

The public inspector of the x402 market. It asks every paid endpoint with real demand for its offer, without
paying, the way a buyer agent's first call does. It publishes who asks the listed price and pays the listed
address, and it proves every figure in an open book that anyone can check with one command.

Agoranome: fair markets for machines. We build the tools that help AI agents find, judge and trust the services
they pay for, and we pledge 15% of what we earn to a public cause.

This is phase 1 of the plan, "Prove": the sheet, the change log, the open book and its verifier. Nothing here is
sold. The tools are free, and the published sheets are under CC BY 4.0.

One book holds the sheets of several markets: x402 (rule `sheet-1`) and MPP, the Machine Payments Protocol (rule
`mpp-1`). Skyfire is next.

## Check a sheet in one command

```sh
pip install "git+https://github.com/Agoranome/agoranome-inspector"
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
  (on the same network and asset, any scheme, when none has the same scheme). Its price is `above_listed` when any
  candidate asks more than every amount the listing states for that network, asset and scheme, because a buyer
  agent may be asked to pay it; else `as_listed` when a candidate asks exactly the listed amount; else
  `below_listed`. Its pay-to is `as_listed` when every candidate pays an address the listing states there,
  `different` when any does not.
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
- **Strict formats.** A field that does not look like what it is is dropped, so that no seller can put a sentence
  (an instruction aimed at buyer agents, say) into a signed sheet: a network must be a CAIP-2 id or an x402 v1
  name, a scheme a short word, an asset or address hex after `0x` or letters, digits and `. _ : -` only (at most 80),
  and a pay-to on an EVM network a 20-byte address. An option missing a field is not payable.

A rule never changes once a sheet is published under it. A new rule gets a new name, and each sheet names the
rule it was judged by, so an old sheet always verifies under its own rule.

### What the sheet cannot see

- **What a paying buyer is asked.** An endpoint can tell the inspector apart (its User-Agent says what it is, and
  it runs from GitHub's addresses) and answer it differently. The sheet records what the endpoint answered the
  inspector, unpaid. Paid checks and amounts read from settled payments are later phases.
- **A price set by method.** An x402 endpoint is asked with GET, and with POST only when GET does not answer 402.
- **A seller that changes its answer on every ask** gets `varies`, which is published but never `false`.

### What the sheet does not publish

Coinbase's developer terms limit sharing data from its tools without written permission. So a published row
carries the seller's own statements and answers, and not the index's payer and call counts. The counts are used
only to choose who is on the sheet, and they stay in the operator's private run file. `sheet
--publish-index-counts` puts them in the rows, and should only be used once Coinbase has said yes in writing.

## The MPP sheet

One row for each paid endpoint in the public MPP catalog (`https://mpp.dev/api/services`), except paths that need
parameters filled in. The catalog states no demand, so the sheet claims none. Each endpoint is asked with the
HTTP method the catalog lists (GET or POST; other methods are not asked). An MPP endpoint answers 402 with one
`WWW-Authenticate: Payment` challenge for each way it can be paid; its `request` names the amount, the currency
and the recipient.

Many MPP endpoints check the request before they quote a price, as one whose price depends on the request must:
asked with an empty body, half of a trial's sample answered 400 naming a required field. So, as a buyer agent
would, the inspector reads the service's own OpenAPI document (`/openapi.json` on the endpoint's host) and sends
the example request it gives for that path and method: its example body and its required query parameters'
examples, or values built from the schema's own examples, defaults and enums. The row says which was sent
(`seen.request`: `seller_example` or `empty`); the example itself is sent, never published, and nothing is paid.
An endpoint that still answers 400 or 422 is `wants_input`: it wanted a request the inspector could not form. That
is not a failing, is not judged, and does not count as an unanswered ask in the check before signing.

The rule `mpp-1` compares as `sheet-1` does, with the payment method in the place of the network, the currency in
the place of the asset and the intent in the place of the scheme. The catalog names no recipient, so the recipient
is recorded and its changes logged, but never judged (`pay_to` is `not_listed`, and a matching price is enough for
`matches_listing: true`). A price the catalog marks `dynamic` is not judged. The realm and description a challenge
carries are free text and are not kept. A row's `resource` is the method and the URL
(`POST https://example.com/v1/answer`), so an endpoint asked two ways has two rows.

## The change log

What changed between two sheets, computed from the two sheets alone: `price_cut`, `price_raised`,
`listed_price_changed`, `pay_to_changed`, `went_dark`, `came_back`, `verdict_changed`, `joined` and `left`.
Free and public. The lab sold this as a $1 watch.

## Operator links

Beside each sheet, `links/<id>.json` says which hosts one operator seems to run, from the newest sheet of each
market alone. Hosts whose live offers ask payment to the same address (an x402 pay-to or an MPP recipient) are
linked, and hosts joined that way form one operator. An address that more than 5 hosts share is a platform's (a
processor's or a facilitator's) and links nobody; it is listed with its host count. A host that sells in more than
one market is listed with its rows in each. Every link carries its evidence. A link is a fact beside the rows,
never a verdict: no row's verdict changes because of it. The verifier rebuilds the file from the sheets.

## The shelf report card

The sheets grade sellers. The shelf card grades the shelves buying agents shop from: Coinbase's x402 Bazaar, the
same index as AWS Bedrock AgentCore's agents reach it, the MPP catalog and Skyfire's directory. By the rule
`shelf-1`, each shelf answers five questions:

| Question | How it is answered |
| --- | --- |
| Open: can anyone read the whole shelf, without an account? | From the shelf's own documents |
| Rank: is the rule that orders a search published, with nothing a seller can pay for? | From its documents |
| Matches: do the listings match what the sellers ask when asked? | Measured: the share of payable offers judged on price that asked no more than listed (and, on x402, to the listed pay-to), from the newest sheet; yes at 95%, partly at 80% |
| Delivery: does the shelf show whether a seller delivers? | From its documents |
| Dispute: can a buyer dispute a charge through the shelf? | From its documents |

Yes is 2 points, partly 1, no or unknown 0; A at 8 of 10, B at 6, C at 4, D below. Each fact carries its source and
the day it was read, and is a plain statement of what was read. A shelf that finds a fact wrong can point to its
documents: the correction is a new entry and the card is graded again. `agoranome-inspector shelf <site>` adds an
entry only when a fact or a sheet behind the card changed, and the verifier recomputes the card from the entry and
the sheets the book holds. The card is `shelves.json` on the site.

## The 15% pledge

Agoranome pledges 15% of what it earns to a public cause, paid once a month from its own receiving address to the
cause's public address in USDC on Base. The lab's ledger (`/impact/ledger`) states each month's settled revenue,
the part that owes the pledge, what is owed and the transfers made. Each weekly run, `anchor-lab` copies the
figures into the book as a `pledge` entry, with a hash of the page as read, whenever they changed. Three checks:

1. owed = ceil(counted x 1500 / 10000) for each month, the lab's own rule;
2. given = the sum of the month's verified transfers, and a month is `kept` exactly when given >= owed;
3. with `verify --chain <Base RPC URL>`, each transfer's transaction holds a USDC Transfer to the cause's address
   of at least its stated amount.

Figures that fail the first two checks are refused, not signed. The figures are the lab's: the inspector checks
their arithmetic and the transfers, and `verify-receipt` checks any receipt against its month's root. Until a cause
is named, what is owed is kept and shown as outstanding. The figures are `pledge.json` on the site.

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
  `links` (the operator links, from the newest sheet of each market);
  `anchor` (the lab's monthly receipt roots as read on a day); `pledge` (the 15% pledge's figures as the lab's
  ledger states them); `shelf` (the shelf report card, its facts and the sheets it was measured from); `note` (a
  correction, a dispute and its answer, a change of method). Nothing is edited or removed. A correction is a new entry.

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
`changes/<id>.json`, `links/<id>.json`, `shelves.json`, `pledge.json` and `index.html`. A sheet's id names its market and day (`x402-2026-11-16`). Each change log
compares a sheet with the sheet just before it in the same market, and the verifier checks that it does. With no
`--id`, `verify` checks the newest sheet of each market.

## Running the inspector

```sh
agoranome-inspector keygen --out inspector-key.pem        # keep it secret; publish the kid it prints
export INSPECTOR_SIGNING_KEY="$(cat inspector-key.pem)"   # or pass --key-file
agoranome-inspector run site/ --private private/          # read the index, ask, judge, publish
agoranome-inspector shelf site/                           # grade the shelves from the newest sheets
agoranome-inspector anchor-lab site/                      # the lab's receipt roots and the pledge's figures
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

1. **Secrets and variables, Actions, secret `INSPECTOR_SIGNING_KEY`**: the whole PEM file of the book's signing key,
   made with `agoranome-inspector keygen --out inspector-key.pem`, from its `-----BEGIN PRIVATE KEY-----` line to
   its `-----END PRIVATE KEY-----` line (on a Mac, `pbcopy < inspector-key.pem` copies it). Not the kid: that is
   public. Keep the file somewhere safe and offline. Until the secret is set, the workflow measures and publishes
   nothing.
2. **Secrets and variables, Actions, variable `INSPECTOR_FIRST_KID`** (optional): the kid `keygen` printed. The run
   then refuses to publish a book whose first key is any other.
3. **Pages**: source "Deploy from a branch", branch `gh-pages`, folder `/ (root)`. The branch exists after the first
   run. The site is then at `https://agoranome.github.io/agoranome-inspector/`.

Each market in the repository variable `RUN_MARKETS` (`x402 mpp` when it is not set; `x402` for x402 alone) runs
in turn into the same book. A market whose run fails publishes nothing that week; the others are still published,
and the job then fails so that GitHub tells the owner.

**The check before signing.** The verifier proves the book is consistent, not that a week's reading is sound, and
the book only grows. So `run` holds a sheet unpublished, and the job fails so that GitHub tells the owner, when the
index was not read completely (short by more than one listing in a thousand: the index is live and changes
while it is paged), the sheet has no rows, more than 25% of the endpoints asked gave no answer at all,
or, against the last sheet of the same market, the row count moved by more than 30% or the payable share by more
than 10 points. Other markets are still published. After looking, start the workflow by hand with "publish
anyway"; the book then carries a note saying the sheet was published past the check, and why.

The private run file, with the index's payer and call counts, is written outside the site and is discarded with
the runner. GitHub turns off a schedule in a public repository after 60 days without activity; if it ever does,
turn it on again in the Actions tab.

### Model uses, capped at $20 a month

With the secret `ANTHROPIC_API_KEY` set, three jobs use a model (`claude-opus-5-5` unless the repository variable
`INSPECTOR_MODEL` names another), each only after a sheet is published and never in its way:

- **The weekly note.** After the weekly run has published, a model writes a short note on the week from the counts
  in the signed book (no row, host, address or seller's text is shown to it). Code checks that every number in the
  note is one of those counts, and drops the note if one is not. It is written to `notes/<sheet id>.md` on the
  site, outside the book, and says it was written by a model.
- **The run doctor.** When the weekly run is held by the check before signing or fails, the job opens an issue with
  the held reasons and the end of the log, and a model's reading of them. Without a model the issue carries the
  facts alone.
- **The monthly red-team** (`.github/workflows/red-team.yml`, on the 2nd). A model reads this repository's code
  for ways a seller, a network or a mistake could make a sheet wrong or the run unsafe. The findings are sealed
  (AES-256-GCM, key derived from the signing key) before they go into a public issue, so an unfixed weakness is
  not shown to everyone. Read them with
  `gh issue view N --json body -q .body | agoranome-inspector reveal --key-file inspector-key.pem`.

No model decides a verdict, sits in the publishing path, or reads sellers' words, and the measuring step never
sees the model key. Every model call can fail and the sheet still publishes unchanged.

**The cap is in code** (`src/agoranome_inspector/models.py`). Each call's worst case (its counted input and its
`max_tokens`, at the highest prices any model that may serve it charges) is written to a spend ledger before the
call, and a call that would take the month past $20 is not made; after the call, the reservation is replaced by
the cost of the usage returned. The ledger is `spend.jsonl` on the branch `model-spend`, append-only, and the jobs
that use it run one at a time. With no ledger, or a damaged one, no call is made. `agoranome-inspector spend
--ledger spend.jsonl` shows the month's spend. As a second guard, set a $20 monthly spend limit on the API key's
workspace in the Claude Console. Two more model uses (a buyer-model test and a one-off verdict-influence run) come
with the fair pick in phase 2.

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
