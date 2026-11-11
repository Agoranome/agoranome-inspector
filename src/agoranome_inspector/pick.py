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

"""The fair pick: for a job and a budget, the paid endpoints that fit, ranked by the published rule `pick-1`.

A buying agent says what it needs done ("weather forecast for a city") and what it will pay at most. The pick
answers with the listings that fit, in an order no seller can pay for:

  1. In the running: the endpoint gave an offer an agent can pay on the newest sheet, with a price per request
     in US dollars (USDC, or a dollar stablecoin MPP names), at or under the budget, and its words match the job
     at least half as well as the best match does (BM25, below).
  2. Honest on price first: those that asked what they list, then those not judged (the price depends on the
     request, or two asks differed), then those that asked more than they list or named another pay-to.
  3. Signs of delivery next. Under pick-1 the one sign is a Fair Offer block, the seller's published promise to
     settle only on delivery. Buyers' reports tied to a payment and repeat buyers read from the chain join under
     a later rule, never this one.
  4. Then the lower price, then the better match, then the resource's address, so every tie is broken the same way.

The match is Okapi BM25 (k1 1.2, b 0.75) over each listing's words: its description, name, tags and address,
lower case, stop words dropped, a light suffix rule, each word counted at most three times and at most 64
distinct words kept. The words are published sorted, so a seller's sentences are never republished and no
instruction written in a listing survives into the pick. Scores are rounded to six places before they are compared.

Each week, with each sheet, the book gets a `pick` entry naming the sheet and the hash of the pick table: one row
for each listing in the running, with the fields the order uses and its words. The verifier recomputes every row
but the words from the sheet; the words are checked for form, and they came from the index the same day. Anyone
can run the pick on the published table and must get the same order.
"""

import math
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from agoranome_inspector import networks

RULE = "pick-1"
KIND = "agoranome.pick-table"
FORMAT = 1
K1, B = 1.2, 0.75
BAND = 0.5              # in the running: a match at least this share of the best match
MAX_WORDS = 64          # distinct words kept from one listing
MAX_TF = 3              # times one word counts in one listing
MAX_TEXT = 4000         # characters read from one text of a listing
MAX_JOB = 500
LIMIT, MAX_LIMIT = 10, 50
PLACES = 6

TEMPO_DOCS = "https://tempo.xyz/developers/docs/guide/bridge-bungee"
# Dollar prices an MPP challenge can name, keyed by (payment method, currency as compared), with their decimals.
# The four Tempo stablecoins are the ones Tempo's own documents list; MPP's Stripe method names "usd" in cents.
MPP_USD = {
    ("tempo", "0x20c0000000000000000000000000000000000000"): 6,     # pathUSD
    ("tempo", "0x20c000000000000000000000b9537d11c60e8b50"): 6,     # USDC.e
    ("tempo", "0x20c00000000000000000000014f22ca97301eb73"): 6,     # USDT0
    ("tempo", "0x20c0000000000000000000006a37da5c996874be"): 6,     # OUSD
    ("evm", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"): 6,       # USDC on Base
    ("solana", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"): 6,  # USDC on Solana
    ("stripe", "usd"): 2,
}
PER_REQUEST_INTENTS = ("charge", None)

HONEST = {0: "asked what it lists", 1: "not judged (the price depends on the request, or two asks differed)",
          2: "asked more than it lists, or named another pay-to"}

METHOD = [
    "In the running: the row gave an offer an agent can pay on the newest sheet of its market, with a price per "
    "request in US dollars (USDC on a main network for x402; for MPP a charge in one of the dollar currencies "
    "listed in MPP_USD), at or under the budget when one is given, and its BM25 match to the job is at least half "
    "the best match among rows in the running.",
    "Price: the cheapest dollar option of an answer; when the endpoint was asked twice, the higher of the two "
    "answers' cheapest options, the price a buyer may be asked.",
    "Order: honest (0 asked what it lists, 1 not judged, 2 asked more or another pay-to), then delivery (0 a Fair "
    "Offer block, 1 none), then price, then match (higher first), then the resource, as text.",
    "Match: Okapi BM25 with k1 1.2 and b 0.75 over the rows ranked together, idf ln(1 + (N - df + 0.5) / (df + "
    "0.5)), each job word counted once, scores rounded to 6 places.",
    "Words: lower case runs of a-z and 0-9 from the listing's description, name, tags and address, stop words "
    "and words of one letter or only digits dropped, a light suffix rule (ies to y; ches, shes, sses, xes, zes "
    "lose es; ing and ed dropped; a final s dropped unless ss, us or is), each word at most 3 times, the 64 most "
    "frequent kept (ties by the word), published sorted.",
]

_WORD = re.compile(r"[a-z0-9]+")
WORD = re.compile(r"^[a-z0-9]{2,24}$")
# The lab's front-door stop words (copied, not imported), and the parts of a web address that say nothing.
STOP = frozenset("""a about above after again all am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having he her
here hers him his how i if in into is it its itself just me more most my myself no nor not now of off on once only
or other our ours out over own same she should so some such than that the their them then there these they this
those through to too under until up very was we were what when where which while who whom why will with would you
your yours yourself please want need let get make give tell find
http https www com net org io xyz app dev html json php api""".split())


def _stem(word: str) -> str:
    def base(n: int) -> bool:
        return len(word) - n >= 3

    if word.endswith("ies") and base(3):
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "sses", "xes", "zes")) and base(2):
        return word[:-2]
    if word.endswith("ing") and base(3):
        return word[:-3]
    if word.endswith("ed") and base(2):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and base(1):
        return word[:-1]
    return word


def tokens(text: Optional[str]) -> List[str]:
    """The content words of a text, in order: lower case, stop words dropped, stemmed."""
    found = _WORD.findall(str(text or "")[:MAX_TEXT].lower().replace("_", " ").replace("-", " "))
    out = []
    for w in found:
        if w in STOP or w.isdigit() or not 2 <= len(w) <= 24:
            continue
        w = _stem(w)
        if WORD.match(w) and w not in STOP:
            out.append(w)
    return out


def words(texts: Iterable[Any]) -> List[str]:
    """A listing's words as published: each at most MAX_TF times, the MAX_WORDS most frequent, sorted."""
    counts = Counter(t for text in texts for t in tokens(text if isinstance(text, str) else None))
    kept = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_WORDS]
    return sorted(w for w, c in kept for _ in range(min(c, MAX_TF)))


def words_ok(found: Any) -> bool:
    """Whether a published word list has the form `words` gives."""
    if not isinstance(found, list) or found != sorted(found):
        return False
    counts = Counter(found)
    return (len(counts) <= MAX_WORDS and all(isinstance(w, str) and WORD.match(w) and w not in STOP
                                             for w in counts) and all(c <= MAX_TF for c in counts.values()))


def _address_texts(url: str) -> List[str]:
    parts = urlsplit(url or "")
    return [(parts.hostname or "").replace(".", " "), parts.path.replace("/", " ")]


def x402_words(item: Dict[str, Any]) -> List[str]:
    """The words of one Bazaar index item: only the texts named here are read."""
    texts: List[Any] = [item.get("description"), item.get("serviceName"), item.get("name")]
    texts += [t for t in item.get("tags") or [] if isinstance(t, str)][:32]
    for option in (item.get("accepts") or [])[:16]:
        if isinstance(option, dict):
            texts.append(option.get("description"))
    meta = item.get("metadata")
    if isinstance(meta, dict):
        texts += [meta.get("description"), meta.get("name"), meta.get("title")]
    texts += _address_texts(str(item.get("resource") or ""))
    return words(texts)


def mpp_words(service: Dict[str, Any], endpoint: Dict[str, Any], url: str) -> List[str]:
    """The words of one MPP catalog endpoint: its service's name, description and categories, and its own."""
    texts: List[Any] = [service.get("name"), service.get("id"), service.get("description"),
                        endpoint.get("description"), endpoint.get("summary"), endpoint.get("name")]
    texts += [c for c in service.get("categories") or [] if isinstance(c, str)][:16]
    texts += _address_texts(url)
    return words(texts)


# --- The table: one row for each listing in the running, from a sheet ------------------------------------------

def _usd_text(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def _x402_cheapest(options: List[Dict[str, Any]]) -> Optional[Tuple[Decimal, Dict[str, Any]]]:
    found = []
    for o in options or []:
        net, asset = o.get("network"), o.get("asset")
        if networks.is_testnet(net) or not o.get("pay_to"):
            continue
        usd = networks.usd(net, asset, o.get("amount"))
        if usd is not None:
            found.append((Decimal(usd), {k: o.get(k) for k in ("scheme", "network", "asset", "amount", "pay_to")}))
    return min(found, key=lambda f: (f[0], f[1]["network"] or "", f[1]["pay_to"] or "")) if found else None


def _mpp_cheapest(options: List[Dict[str, Any]]) -> Optional[Tuple[Decimal, Dict[str, Any]]]:
    found = []
    for o in options or []:
        places = MPP_USD.get((o.get("method"), o.get("currency")))
        if places is None or o.get("intent") not in PER_REQUEST_INTENTS or o.get("amount") is None \
                or not o.get("recipient"):
            continue
        found.append((Decimal(int(o["amount"])).scaleb(-places),
                      {k: o.get(k) for k in ("method", "intent", "currency", "amount", "recipient")}))
    return min(found, key=lambda f: (f[0], f[1]["method"] or "", f[1]["recipient"] or "")) if found else None


def price(market: str, row: Dict[str, Any]) -> Optional[Tuple[Decimal, Dict[str, Any]]]:
    """The dollar price a buyer may be asked, and the option that asks it; None when no answer named one."""
    seen = row.get("seen") or {}
    cheapest = _mpp_cheapest if market == "mpp" else _x402_cheapest
    answers = [seen] + ([seen["again"]] if isinstance(seen.get("again"), dict) else [])
    found = [c for c in (cheapest(a.get("options") or []) for a in answers) if c is not None]
    return max(found, key=lambda f: f[0]) if found else None


def honest(verdict: Dict[str, Any]) -> int:
    matches = verdict.get("matches_listing")
    return 0 if matches is True else 2 if matches is False else 1


def table_row(market: str, row: Dict[str, Any], found_words: List[str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """A sheet row as the pick reads it, or None and why it is not in the running."""
    if (row.get("verdict") or {}).get("answer") != "payable":
        return None, "not_payable"
    priced = price(market, row)
    if priced is None:
        return None, "no_usd_price"
    usd, option = priced
    seen = row.get("seen") or {}
    return {
        "resource": row["resource"],
        "market": market,
        "url": row.get("url") or row["resource"],
        "method": row.get("http_method") or seen.get("method"),
        "host": row.get("host"),
        "category": row.get("category"),
        "price_usd": _usd_text(usd),
        "pay": option,
        "honest": honest(row["verdict"]),
        "delivery": 0 if seen.get("fair_offer") else 1,
        "fair_offer": seen.get("fair_offer"),
        "words": list(found_words),
    }, "in"


def table(sheet: Dict[str, Any], words_by_resource: Dict[str, List[str]]) -> Dict[str, Any]:
    """The pick table of one sheet, from its rows and the words each listing had the same day."""
    from agoranome_inspector import sheet as sheet_lib

    market = sheet_lib.market_of(sheet)
    rows, left_out = [], Counter()
    for r in sheet.get("rows") or []:
        found, why = table_row(market, r, words_by_resource.get(r["resource"]) or [])
        if found is None:
            left_out[why] += 1
        else:
            rows.append(found)
    rows.sort(key=lambda r: r["resource"])
    return {"kind": KIND, "format": FORMAT, "rule": RULE, "market": market, "sheet": sheet["id"],
            "method": METHOD, "left_out": dict(sorted(left_out.items())), "rows": rows}


def check_table(found: Dict[str, Any], sheet: Dict[str, Any]) -> List[str]:
    """Recompute a pick table from its sheet; the words can only be checked for form."""
    if found.get("rule") != RULE:
        return [f"unknown pick rule {found.get('rule')!r}"]
    if found.get("sheet") != sheet.get("id"):
        return [f"the pick table names sheet {found.get('sheet')}, not {sheet.get('id')}"]
    by_resource = {r.get("resource"): r for r in found.get("rows") or []}
    if len(by_resource) != len(found.get("rows") or []):
        return ["the pick table names a resource twice"]
    bad = [r for r, row in by_resource.items() if not words_ok(row.get("words"))]
    if bad:
        return [f"{len(bad)} row(s) of the pick table carry words not in the published form"]
    again = table(sheet, {r: row["words"] for r, row in by_resource.items()})
    if {k: v for k, v in again.items() if k != "method"} != {k: v for k, v in found.items() if k != "method"}:
        return ["the pick table does not follow from its sheet"]
    return []


# --- The pick ------------------------------------------------------------------------------------------------

def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        found = Decimal(str(value).strip().lstrip("$"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"budget {value!r} is not a number of dollars")
    if not found.is_finite() or found < 0:
        raise ValueError(f"budget {value!r} is not a number of dollars")
    return found


class Index:
    """BM25 over the rows ranked together."""

    def __init__(self, rows: List[Dict[str, Any]]):
        self.counts = [Counter(r["words"]) for r in rows]
        self.lengths = [len(r["words"]) for r in rows]
        self.avg = (sum(self.lengths) / len(rows)) if rows else 0.0
        df: Counter = Counter()
        for c in self.counts:
            df.update(c.keys())
        n = len(rows)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}

    def score(self, i: int, query: List[str]) -> float:
        counts = self.counts[i]
        norm = K1 * (1 - B + B * self.lengths[i] / (self.avg or 1.0))
        s = 0.0
        for w in sorted(set(query)):
            f = counts.get(w, 0)
            if f:
                s += self.idf[w] * f * (K1 + 1) / (f + norm)
        return round(s, PLACES)


def rank(tables: List[Dict[str, Any]], job: str, budget_usd: Any = None, *, market: Optional[str] = None,
         limit: int = LIMIT) -> Dict[str, Any]:
    """The fair pick for a job and a budget over the given pick tables."""
    job = str(job or "").strip()[:MAX_JOB]
    query = sorted(set(tokens(job)))
    budget = _decimal(budget_usd)
    limit = max(1, min(int(limit or LIMIT), MAX_LIMIT))
    chosen = [t for t in tables if market in (None, "", t.get("market"))]
    rows = [r for t in chosen for r in t.get("rows") or []]
    index = Index(rows)
    left_out: Counter = Counter()
    scored = []
    for i, r in enumerate(rows):
        if budget is not None and Decimal(r["price_usd"]) > budget:
            left_out["over_budget"] += 1
            continue
        s = index.score(i, query) if query else 0.0
        if s > 0:
            scored.append((s, r))
        else:
            left_out["no_match"] += 1
    best = max((s for s, _ in scored), default=0.0)
    floor = round(best * BAND, PLACES)
    running = [(s, r) for s, r in scored if s >= floor]
    left_out["weak_match"] += len(scored) - len(running)
    running.sort(key=lambda sr: (sr[1]["honest"], sr[1]["delivery"], Decimal(sr[1]["price_usd"]), -sr[0],
                                 sr[1]["resource"]))
    picked = []
    for n, (s, r) in enumerate(running[:limit], 1):
        picked.append({
            "rank": n, "resource": r["resource"], "market": r["market"], "url": r["url"], "method": r["method"],
            "host": r["host"], "category": r["category"], "price_usd": r["price_usd"], "pay": r["pay"],
            "honest": HONEST[r["honest"]], "delivery": "a Fair Offer block" if r["delivery"] == 0 else None,
            "match": s,
        })
    return {
        "rule": RULE, "job": job, "words": query, "budget_usd": None if budget is None else _usd_text(budget),
        "market": market or None,
        "from": [{"market": t.get("market"), "sheet": t.get("sheet"), "entry": t.get("entry")} for t in chosen],
        "in_running": len(running), "shown": len(picked),
        "left_out": {k: left_out[k] for k in ("over_budget", "no_match", "weak_match")},
        "picked": picked,
        "note": None if query else "The job has no words the pick can match; say what the endpoint should do.",
    }
