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

## The fair pick

For a job in plain words and the most a buyer will pay for one request, the endpoints that fit, in an order no
seller can pay for. The rule is `pick-1` (`src/agoranome_inspector/pick.py`):

1. **In the running:** the row gave an offer an agent can pay on the newest sheet of its market, with a price per
   request in US dollars (USDC on a main network for x402; for MPP a charge in USDC, pathUSD, USDT0, OUSD or by
   card in dollars), at or under the budget, and its words match the job at least half as well as the best match.
2. **Honest on price first:** those that asked what they list, then those not judged (the price depends on the
   request, or two asks differed), then those that asked more than they list or named another pay-to.
3. **Signs of delivery next.** Under `pick-1` the only sign is a Fair Offer block, the seller's published promise
   to settle only on delivery. Buyers' reports tied to a payment, and repeat buyers read from the chain, will come
   under a later rule, never by changing this one.
4. **Then the lower price**, then the better match, then the address, so every tie breaks the same way.

The match is Okapi BM25 (k1 1.2, b 0.75) over each listing's words: its description, name, tags and address,
lower case, stop words dropped, a light suffix rule, each word counted at most 3 times and at most 64 distinct
words kept. Stuffing a description with a word buys little: it only has to clear half the best match, and the
order inside the running is honesty, delivery and price. The words are published sorted, so a seller's sentences
are never republished and no instruction written in a listing reaches a buying agent through the pick.

With each sheet, the weekly run writes `picks/<id>.json`, one row for each listing in the running with the fields
the order uses and its words, and a `pick` entry in the book with its hash. The verifier recomputes every field
but the words from the sheet, and checks the words' form. Anyone gets the same order:

```bash
agoranome-inspector pick https://agoranome.github.io/agoranome-inspector/ "weather forecast for a city" --budget 0.01
agoranome-inspector mcp      # the same as two MCP tools on stdio: fair_pick and seller_row
```

`seller_row` answers one endpoint's row on the newest sheet with its Merkle proof against the signed root. Both
tools are free and read-only. For an MCP client:

```json
{"mcpServers": {"agoranome-inspector": {"command": "agoranome-inspector", "args": ["mcp"]}}}
```

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

**Small sums, `carry-1`.** One transfer a month costs a fee whatever its size, so a month that leaves under $1 owed
carries over and shows as `carried`; nothing is carried past the end of a quarter. Over the months the book runs a
balance of what was owed less what was given: `kept` when it is nothing, `carried` when under $1 inside a quarter,
`owed` otherwise, and `late` once a cause is named and 45 days have passed since the month (or, for a carried
month, its quarter) ended. The book refuses figures whose standings don't follow the rule, and `verify` warns of
a late month.

## The accounts

What Agoranome earns outside x402, in the same book, so the 15% is owed on all of it (`accounts-1`,
`src/agoranome_inspector/accounts.py`). Each is a `statement` entry naming its kind, payer, month, amount in
dollars and the SHA-256 of the document behind it (the payout statement, the licence, the award notice), with its
https address when it is public. The book names every licensee and funder, and what each paid:

| Kind | Earned (counts toward the $47.06 bar) | Pledged |
| --- | --- | --- |
| `payout` (a marketplace's payout to Agoranome) | yes | yes |
| `licence` (a platform licence, at its public list price) | yes | yes |
| `prize` (a grant with no strings, a prize, a reward) | yes | yes |
| `grant` (for named public work, paid by milestone) | no | only with the funder's written agreement, whose hash the statement carries |
| `credit` (cloud or API credit) | no | no |

A grant or a prize goes in only when the funder passed the five tests: a programme with public rules others can
apply to, no say over a figure, a grade or the method, results that stay open, the amount and each payment in the
book, and the funder graded like everyone else. A licence names its public list price. Sponsors are not a kind:
Agoranome takes none. Whether a grant carries the pledge is the concept's proposal, awaiting Shariar's ruling; a
change would be a new rule, never a quiet edit.

At each month's end, `close` adds a `close` entry (`close-1`): every source for the month (x402 from the newest
pledge figures, then each statement) with what each owes, and their sum as the month's total owed. The pledge's
standing then runs on that total. Statements go in through the workflow `Accounts` (Actions tab, "Run workflow",
with the statement's fields), which also closes the past months on the first three days of each month. The
verifier rebuilds each statement and close; the accounts are `accounts.json` on the site.

**The gates.** The plan's stop rules are tracked by the lab at `https://api.agoranome.com/gates.json`: one outside
sign of use within 60 days of reaching the shelves, a data good retired under 10 payers at day 60, earned money
covering $47.06 a month by day 90, and the ask test. The lab sees only its own receipts, so each weekly run,
`gates <site>` keeps the lab's statuses and completes the money gate from the newest closed month, every earned
source together. A grant is not earned and never passes it. A `gates` entry is added only when something changed;
the verifier recomputes the money figure, and the reading is `gates.json` on the site.

## Signs from the chain

Who comes back, read from Base and never from a seller's words (`signs-1`, `src/agoranome_inspector/signs.py`).
With a Base RPC address (the repository secret `BASE_RPC`), the weekly run reads the USDC transfers of the last 30
days into each pay-to on the newest x402 sheet and counts, for each host: payers, payers that came back (sessions
more than 900 blocks, about 30 minutes, apart), payers that paid five or more other hosts within an hour of paying
it (a sweep, not a choice), and payments from the seller's own addresses. An address named by more than one host
is a platform's and counted apart; a host with more than 20,000 transfers in the window is marked busy and not
read. `signs/<id>.json` holds counts only: no payer is named, and Coinbase's Bazaar figures are never used. The
verifier checks the file against its sheet and, with `--chain`, reads three hosts again.

Signs are facts beside a row. No verdict and no rank under `pick-1` or `best-buy-1` uses them; a later rule will say
so before it does.

## The best buys

Per category on the newest sheets, the ten listings an agent can pay that rank first by `pick-1`'s order with no
job to match: honest on price, then a Fair Offer block, then the lower price (`best-buy-1`,
`src/agoranome_inspector/bestbuy.py`). Each row shows its signs from the chain and its buyers' report counts beside
it, unranked. The weekly run writes `best-buy/<date>.json` and a page; the verifier rebuilds both from the sheets.

## Sellers' disputes

A seller that finds its row wrong says so at the lab (`POST https://api.agoranome.com/disputes`): the row's
resource, the sheet, the field (`price`, `pay_to`, `answer`, `category`, `fair_offer` or `signs`), what it says the
field should be as one short token, and an optional https link to its evidence, signed (EIP-191) by the address the
row asks payment to. `GET /disputes/message` gives the exact words to sign. No free text is taken.

Each weekly run, `disputes <site>` copies new disputes into a `dispute` entry after checking the signer against the
row on that sheet's pick table and, with `eth-account` installed, the signature. The operator answers each one,
once, with the workflow `Answer a dispute` or `answer <site> ID --outcome upheld|not_upheld --reason TEXT`: upheld
means the next sheet or a correction puts the row right. No model reads a dispute or writes an answer.
`disputes.json` on the site lists every dispute with its answer.

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
  `links` (the operator links, from the newest sheet of each market); `pick` (a sheet's pick table, its hash and
  counts);
  `anchor` (the lab's monthly receipt roots as read on a day); `pledge` (the 15% pledge's figures as the lab's
  ledger states them); `shelf` (the shelf report card, its facts and the sheets it was measured from); `reports`
  (buyers' reports copied from the lab, each tied to a payment on Base); `note` (a
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

## Receipts bound to what was delivered

Every paid answer from the lab carries a signed receipt naming the SHA-256 of the RFC 8785 (JCS) form of the result
it came with (`receipt.delivery.sha256`), and the lab's ledger keeps that hash beside the receipt (its proof page
shows it). A buyer can show what it was sold, and anyone can recompute the hash:
`agoranome-inspector check-delivery answer.json`. On a row set paid with x402's `upto` scheme the receipt also names
the ceiling the buyer signed for (`ceiling_atomic`) beside what was charged for the rows delivered (`amount_atomic`).

## Buyers' reports

A buyer that paid an x402 seller can say what it got: delivered, not delivered, a wrong result, charged more than
quoted, or too slow. The lab takes the report (`POST https://api.agoranome.com/reports`) only from the wallet that
paid: the report names the payment's transaction on Base, which must move USDC from the signing wallet to an address
the seller's row on this inspector's newest sheet asks payment to, and the wallet signs the report (EIP-191). One
report per payment, never edited, and no free text: only the outcome.

Each weekly run, `agoranome-inspector reports <site>` copies every report the lab's listing shows that the book
doesn't hold yet into a `reports` entry, with a hash of the page as read. A report the book holds that the lab no
longer lists is named in the next entry's `missing`, so none can be quietly removed. `verify` checks each report
against the pick table of the sheet it names, and with `--chain RPC` reads its payment again on Base. Reports are
signs, not verdicts: no rule counts them yet, and pick-1 doesn't.

## The record that travels

A seller's history on the sheets, in one file it can carry anywhere: to a marketplace listing, a buyer, or a grant
reviewer. `agoranome-inspector record <site> <host> --out record.json` gathers, from every sheet in the book, the
host's rows with their Merkle proofs and the signed book entries they fold into (the sheets' and the key entries').
Nothing else is needed to check it:

```
agoranome-inspector verify-record record.json --key <first key's kid>
agoranome-inspector verify-record record.json --key <kid> --against https://agoranome.github.io/agoranome-inspector/
```

The first recomputes each entry's hash, checks its Ed25519 signature by the key in force at its place in the book,
and folds each row into its sheet's signed root, so a row can't be added, changed, or dropped from a week the
record shows. The second also checks that each entry still stands at its place in the live book. What a record
can't show is a week it leaves out: it says how many sheets the book held when it was made (`book.sheets`), so a
reader can ask for the rest. Rows are what the sheet says, verdicts by the published rules; no grade is added and
nobody can pay to change one.

## The published site

Plain files that any static host can serve: `book.jsonl`, `head.json`, `sheets/<id>.json`, `sheets/<id>.csv`,
`changes/<id>.json`, `links/<id>.json`, `picks/<id>.json`, `signs/<id>.json`, `best-buy/<date>.json`,
`shelves.json`, `pledge.json`, `accounts.json`, `disputes.json`, `gates.json` and `index.html`. A sheet's id
names its market and day (`x402-2026-11-16`). Each change log
compares a sheet with the sheet just before it in the same market, and the verifier checks that it does. With no
`--id`, `verify` checks the newest sheet of each market.

## Running the inspector

```sh
agoranome-inspector keygen --out inspector-key.pem        # keep it secret; publish the kid it prints
export INSPECTOR_SIGNING_KEY="$(cat inspector-key.pem)"   # or pass --key-file
agoranome-inspector run site/ --private private/          # read the index, ask, judge, publish
agoranome-inspector shelf site/                           # grade the shelves from the newest sheets
agoranome-inspector anchor-lab site/                      # the lab's receipt roots and the pledge's figures
agoranome-inspector reports site/                         # buyers' reports, each tied to a payment on Base
agoranome-inspector check-delivery answer.json            # a paid lab answer's receipt names its result's hash
agoranome-inspector signs site/ --rpc "$BASE_RPC"         # who comes back, read from Base (counts only)
agoranome-inspector disputes site/                        # sellers' disputes, each signed by the row's pay-to
agoranome-inspector best-buy site/                        # the best buys per category
agoranome-inspector statement site/ --type payout ...     # money earned outside x402, with its document's hash
agoranome-inspector close site/                           # each finished month's sources and total owed
agoranome-inspector gates site/                           # the plan's gates, the money gate from the accounts
agoranome-inspector answer site/ d-... --outcome not_upheld --reason "..."
agoranome-inspector verify site/ --all --strict           # warnings (a late pledge month) fail too
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
4. **Secrets and variables, Actions, secret `BASE_RPC`** (optional): a Base mainnet RPC address for the signs from
   the chain. Without it the run skips them and says so.

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

With the secret `ANTHROPIC_API_KEY` set, five jobs use a model (`claude-opus-5-5` unless the repository variable
`INSPECTOR_MODEL` names another), each after the sheets are published or apart from them, never in their way:

- **The weekly note.** After the weekly run has published, a model writes a short note on the week from the counts
  in the signed book (no row, host, address or seller's text is shown to it). Code checks that every number in the
  note is one of those counts, and drops the note if one is not. It is written to `notes/<sheet id>.md` on the
  site, outside the book, and says it was written by a model.
- **The run doctor.** When the weekly run is held by the check before signing or fails, the job opens an issue with
  the held reasons and the end of the log, and a model's reading of them. Without a model the issue carries the
  facts alone.
- **The buyer test** (weekly, after the note). A model reads Agoranome's own paid listings as a buying agent would:
  only the lab's own words, from `https://api.agoranome.com/openapi.json` (the command refuses any other host), each
  beside what the newest sheet measured for it. For each it gives the job a buyer would type to find it, what it
  expects to get, whether the listing as written fits what was measured, and a truthful rewrite of at most 300
  characters. Code then runs the fair pick for that job (no model), to see whether a buyer who asks for it finds
  the listing, and again with the rewrite's words; and drops any rewrite with a number not in the listing or the
  measurements, a claim of standing, or words aimed at agents. It is written to `buyer-test/<sheet id>.json`,
  outside the book. The rewrites are drafts for the lab's operator; nothing applies them.
- **The verdict study** (once, by hand: `.github/workflows/verdict-study.yml`). Does a verdict shown beside an offer
  move a buying model? Ten jobs, each with three offers Agoranome wrote on hosts under `.example`; in each set the
  offer that lists the lowest price asked more than it lists. Each set is shown in three orders, with and without
  the inspector's verdict beside every offer, and the model picks one. Code counts the picks and runs Fisher's
  exact test; the result goes to `studies/verdict-influence-<day>.json` on the site and the run's artifact. Sixty
  short calls, well under a dollar at the listed prices.
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
workspace in the Claude Console.

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
