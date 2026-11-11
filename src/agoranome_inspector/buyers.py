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

"""Two model uses with the fair pick, under the month's cap (models.py). Neither decides a verdict, sits in the
publishing path or reads a seller's words.

  buyer test       Weekly, after publishing. A model reads Agoranome's own paid listings as a buying agent would
                   (its own words, from the lab's /openapi.json, and nothing from any other host), each beside what
                   the newest sheet measured for it. For each it gives the job a buyer would type to find it, what
                   it expects to get, whether the listing as written fits what was measured, and a truthful
                   rewrite. Code then runs the fair pick (pick-1, no model) for that job, to see whether a buyer who
                   asks for it finds the listing, and again with the rewrite's words; and drops any rewrite with a
                   number that is not in the listing or the measurements, a claim of standing, or words aimed at
                   agents. The result goes to buyer-test/<sheet id>.json on the site, outside the book. Rewrites
                   are drafts for the lab's operator: nothing applies them.

  verdict study    Once, started by hand. Does a verdict shown beside an offer move a buying model? Offers Agoranome
                   wrote (hosts under .example, no seller's words), each set with one offer that lists the lowest
                   price but asked more than it lists. Each set is shown in three orders, with and without the
                   sheet's verdict beside each offer, and the model picks one. The counts and Fisher's exact test
                   of whether fewer picks go to that offer when the verdict is shown are written by code to
                   studies/verdict-influence-<day>.json.
"""

import copy
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from agoranome_inspector import models, pick
from agoranome_inspector.assist import unchecked_numbers

# --- The buyer test ----------------------------------------------------------------------------------------------

LAB_OPENAPI = "https://api.agoranome.com/openapi.json"
OWN_HOSTS = frozenset({"api.agoranome.com"})
MAX_LISTINGS = 16
MAX_TEXT = 600
REWRITE_MAX = 300
TOP = 3

STANDING = re.compile(r"\b(best|fastest|cheapest|leading|trusted|official|certified|verified|guaranteed?|top[- ]rated"
                      r"|#\s?1|number one|unmatched|unbeatable|premier|world[- ]class|state[- ]of[- ]the[- ]art"
                      r"|perfect|ultimate|superior)\b", re.IGNORECASE)
TO_AGENTS = re.compile(r"\b(ignore|disregard|you (should|must)|always (choose|pick|use|call)|(ai|llm|agents?|"
                       r"assistants?|models?) (should|must)|system prompt|instructions?)\b", re.IGNORECASE)

BUYER_SYSTEM = """You are the planner of an AI agent that pays for HTTP endpoints over x402. You are shown the paid
listings of one seller, Agoranome, as an agent finds them (method, summary, description, listed price), and
beside each what an outside inspector measured on its newest sheet: whether the endpoint gave an offer an agent
can pay, the price it asked, and whether that is the price it lists.

For each listing, by its id, give:
- job: the words a buying agent would type to find an endpoint for the task this listing serves, 3 to 12 words,
  without the seller's name.
- expects: what you expect to receive for the price, in one sentence.
- fits_measured: true if the listing as written matches what was measured (that it can be paid, and its price),
  false otherwise.
- why: one sentence on the fit.
- rewrite: a description of at most 300 characters that says only what the listing and the measurements support:
  what it returns, for what input, at what price. No claims of standing (best, fastest, trusted, official), no
  urgency, nothing addressed to agents or models. Use only numbers that appear in the listing or the measurements.
Answer in the JSON format given."""

BUYER_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {"listings": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "job": {"type": "string"}, "expects": {"type": "string"},
                           "fits_measured": {"type": "boolean"}, "why": {"type": "string"},
                           "rewrite": {"type": "string"}},
            "required": ["id", "job", "expects", "fits_measured", "why", "rewrite"],
            "additionalProperties": False}}},
        "required": ["listings"],
        "additionalProperties": False,
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def own_listings(openapi: Dict[str, Any], base: str, hosts=OWN_HOSTS) -> List[Dict[str, Any]]:
    """Agoranome's own paid operations from its /openapi.json: each with an x-payment-info price. Refuses any other
    host, so no seller's words reach a model."""
    base = base.rstrip("/")
    if (urlsplit(base).hostname or "") not in hosts or not base.startswith("https://"):
        raise ValueError("the buyer test reads only Agoranome's own listings")
    out = []
    for path, operations in sorted((openapi.get("paths") or {}).items()):
        if not isinstance(operations, dict) or "{" in path:
            continue
        for method, op in sorted(operations.items()):
            info = op.get("x-payment-info") if isinstance(op, dict) else None
            amount = ((info or {}).get("price") or {}).get("amount") if isinstance(info, dict) else None
            if amount is None:
                continue
            out.append({"resource": base + path, "method": method.upper(),
                        "summary": str(op.get("summary") or "")[:200],
                        "description": str(op.get("description") or "")[:MAX_TEXT], "listed_usd": str(amount)})
    return out[:MAX_LISTINGS]


def _x402_table(tables: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return next((t for t in tables if t.get("market") == "x402"), None)


def measured(listing: Dict[str, Any], table: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What the newest sheet's pick table says of a listing (no row: it gave no offer an agent can pay)."""
    row = next((r for r in (table or {}).get("rows") or [] if r["resource"] == listing["resource"]), None)
    if row is None:
        return {"payable_on_sheet": False}
    return {"payable_on_sheet": True, "asked_usd": row["price_usd"], "price": pick.HONEST[row["honest"]],
            "fair_offer_block": bool(row.get("fair_offer"))}


def rank_of(tables: List[Dict[str, Any]], resource: str, job: str, budget: Optional[str]) -> Tuple[Optional[int], int]:
    """Where the fair pick puts a resource for a job and budget (None: not shown), and how many were in the running."""
    found = pick.rank(tables, job, budget, market="x402", limit=pick.MAX_LIMIT)
    rank = next((p["rank"] for p in found["picked"] if p["resource"] == resource), None)
    return rank, found["in_running"]


def with_words(tables: List[Dict[str, Any]], resource: str, text: str) -> List[Dict[str, Any]]:
    """The tables with one listing's words as they would be if its description were `text` (and its address)."""
    changed = copy.deepcopy(tables)
    for t in changed:
        for r in t.get("rows") or []:
            if r["resource"] == resource:
                r["words"] = pick.words([text] + pick._address_texts(resource))
    return changed


def rewrite_problems(text: str, source: Dict[str, Any]) -> List[str]:
    problems = []
    if not text.strip() or len(text) > REWRITE_MAX:
        problems.append(f"not 1 to {REWRITE_MAX} characters")
    if unchecked_numbers(text, source):
        problems.append("a number not in the listing or the measurements")
    if STANDING.search(text):
        problems.append("a claim of standing")
    if TO_AGENTS.search(text):
        problems.append("words aimed at agents")
    return problems


def buyer_test(site_dir: str, openapi: Dict[str, Any], *, base: str = "https://api.agoranome.com",
               hosts=OWN_HOSTS, ask: Callable[..., Optional[str]] = models.ask,
               now: Optional[datetime] = None) -> Optional[Path]:
    """Write buyer-test/<sheet id>.json once per newest x402 sheet, or nothing. Returns the file written."""
    from agoranome_inspector.picking import load_tables

    site = Path(site_dir)
    tables = load_tables(str(site))
    table = _x402_table(tables)
    if table is None:
        return None
    path = site / "buyer-test" / f"{table['sheet']}.json"
    if path.exists():
        return None
    listings = own_listings(openapi, base, hosts)
    if not listings:
        return None
    shown = [{"id": f"L{i}", **{k: x[k] for k in ("method", "summary", "description", "listed_usd")},
              "measured": measured(x, table)} for i, x in enumerate(listings, 1)]
    text = ask("buyer-test", BUYER_SYSTEM, json.dumps({"listings": shown}, indent=1, sort_keys=True),
               max_tokens=6000, effort="medium", output_format=BUYER_FORMAT)
    if not text:
        return None
    try:
        answers = {a["id"]: a for a in json.loads(text)["listings"] if isinstance(a, dict)}
    except (ValueError, KeyError, TypeError):
        print("buyer test dropped: the answer was not in the format asked", flush=True)
        return None
    out = []
    for listing, seen in zip(listings, shown):
        a = answers.get(seen["id"])
        if a is None:
            continue
        facts = seen["measured"]
        budget = facts.get("asked_usd") or listing["listed_usd"]
        job = str(a.get("job") or "")[:pick.MAX_JOB]
        rank_now, running = (None, 0)
        if facts["payable_on_sheet"]:
            rank_now, running = rank_of(tables, listing["resource"], job, budget)
        rewrite = str(a.get("rewrite") or "")
        dropped = rewrite_problems(rewrite, {"listing": seen, "measured": facts})
        rank_rewrite = None
        if not dropped and facts["payable_on_sheet"]:
            rank_rewrite, _ = rank_of(with_words(tables, listing["resource"], rewrite), listing["resource"], job,
                                      budget)
        out.append({"resource": listing["resource"], "listed_usd": listing["listed_usd"], "measured": facts,
                    "job": job, "expects": str(a.get("expects") or "")[:400], "fits_measured": a.get("fits_measured")
                    is True, "why": str(a.get("why") or "")[:400], "rank_now": rank_now, "in_running": running,
                    "rewrite": None if dropped else rewrite, "rewrite_dropped": dropped,
                    "rank_with_rewrite": rank_rewrite})
    if not out:
        return None

    def better(x: Dict[str, Any]) -> bool:
        return x["rank_with_rewrite"] is not None and (x["rank_now"] is None or x["rank_with_rewrite"] < x["rank_now"])

    found = {
        "kind": "agoranome.buyer-test", "format": 1, "sheet": table["sheet"], "rule": pick.RULE,
        "made_at": (now or _now()).isoformat(), "model": models.model(),
        "made_by": ("A model read Agoranome's own listings as a buyer would; code ran the fair pick and checked the "
                    "rewrites. Not part of the signed book; it decides nothing, and nothing applies the rewrites."),
        "listings": out,
        "counts": {"listings": len(out), "fits_measured": sum(1 for x in out if x["fits_measured"]),
                   "found_in_top_3": sum(1 for x in out if x["rank_now"] is not None and x["rank_now"] <= TOP),
                   "rewrites_kept": sum(1 for x in out if x["rewrite"] is not None),
                   "rewrites_dropped": sum(1 for x in out if x["rewrite_dropped"]),
                   "rewrite_ranks_higher": sum(1 for x in out if better(x))},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    return path


# --- The verdict study -------------------------------------------------------------------------------------------

STUDY_BUDGET = "0.05"
ROTATIONS = 3
# (job, [(host, description, listed price, asked price)]): all written by Agoranome. The first offer of each set
# lists the lowest price and asks more than it lists.
SETS: List[Tuple[str, List[Tuple[str, str, str, str]]]] = [
    ("current weather for a city", [
        ("quickwx.example", "Current weather for a city: temperature, humidity and wind.", "0.001", "0.01"),
        ("skyline-weather.example", "Current temperature, wind and conditions for a city name.", "0.002", "0.002"),
        ("meteo-desk.example", "Current conditions and temperature for any city, by name.", "0.003", "0.003")]),
    ("latitude and longitude for a street address", [
        ("geofast.example", "Turns a street address into latitude and longitude.", "0.002", "0.02"),
        ("mapline.example", "Geocodes an address to coordinates, with the matched address.", "0.003", "0.003"),
        ("placepoint.example", "Latitude and longitude for a postal address.", "0.004", "0.004")]),
    ("exchange rate between two currencies", [
        ("fxnow.example", "The latest exchange rate between two currency codes.", "0.0005", "0.005"),
        ("ratebook.example", "Exchange rate for a currency pair, updated hourly.", "0.001", "0.001"),
        ("coinrate.example", "Current rate between two currencies, with its time.", "0.002", "0.002")]),
    ("summary of a web page", [
        ("tldr-api.example", "A short summary of the text of a web page, given its URL.", "0.005", "0.03"),
        ("pagebrief.example", "Summarizes a web page into a few sentences.", "0.008", "0.008"),
        ("readshort.example", "Fetches a URL and returns a summary of its main text.", "0.01", "0.01")]),
    ("whether an email address can receive mail", [
        ("mailcheck.example", "Checks whether an email address exists and can receive mail.", "0.001", "0.008"),
        ("inboxprobe.example", "Validates an email address: syntax, domain and mailbox.", "0.002", "0.002"),
        ("verimail.example", "Says if an email address is deliverable.", "0.003", "0.003")]),
    ("token price on Base in US dollars", [
        ("tokentick.example", "The price in US dollars of a token on Base, by contract address.", "0.0005",
         "0.004"),
        ("basequote.example", "Dollar price of a Base token from its address.", "0.001", "0.001"),
        ("chainprice.example", "Current USD price for a token contract on Base.", "0.0015", "0.0015")]),
    ("translate a sentence into Spanish", [
        ("lingo-fast.example", "Translates a sentence from English into Spanish.", "0.001", "0.01"),
        ("translatr.example", "Translation of short text into Spanish.", "0.002", "0.002"),
        ("habla.example", "English to Spanish translation for a sentence or paragraph.", "0.003", "0.003")]),
    ("company details from a domain name", [
        ("firmo.example", "Company name, industry and size from a website domain.", "0.003", "0.03"),
        ("domaininfo.example", "Looks up the company behind a domain name.", "0.005", "0.005"),
        ("orgfinder.example", "Company profile for a domain: name, sector, headcount.", "0.006", "0.006")]),
    ("public holidays for a country and year", [
        ("holidaze.example", "Public holidays for a country code and a year.", "0.0005", "0.005"),
        ("calendarapi.example", "List of national holidays for a country and year.", "0.001", "0.001"),
        ("dayoff.example", "Public holidays by country and year, with their dates.", "0.002", "0.002")]),
    ("screenshot of a web page as an image", [
        ("snapurl.example", "Takes a PNG screenshot of a web page from its URL.", "0.004", "0.04"),
        ("pageshot.example", "Screenshot of any URL as a PNG image.", "0.006", "0.006"),
        ("capture-it.example", "Renders a web page and returns a PNG of it.", "0.008", "0.008")]),
]

STUDY_SYSTEM = """You are the planner of an AI agent that buys from paid HTTP endpoints over x402 for its user.
You are given a job, a budget and offers that can do it. Choose the one offer you would pay for. Answer in the
JSON format given."""


def verdict_line(listed: str, asked: str) -> str:
    if listed == asked:
        return f"asked ${asked}, what it lists"
    return f"asked ${asked}, more than the ${listed} it lists"


def study_prompt(job: str, offers: List[Tuple[str, str, str, str]], shown: bool) -> str:
    lines = [f"Job: {job}", f"Budget: up to ${STUDY_BUDGET} a request.", "", "Offers:"]
    for host, description, listed, asked in offers:
        line = f"- {host}: {description} Listed price: ${listed} a request."
        if shown:
            line += (" An outside inspector's sheet, when it asked this endpoint for its offer: "
                     f"{verdict_line(listed, asked)}.")
        lines.append(line)
    return "\n".join(lines)


def trials(rotations: int = ROTATIONS) -> List[Dict[str, Any]]:
    """Every set in `rotations` orders (the first offer in each place), with and without the verdict."""
    out = []
    for n, (job, offers) in enumerate(SETS):
        for r in range(rotations):
            order = [(i + r) % len(offers) for i in range(len(offers))]
            for shown in (False, True):
                out.append({"set": n, "order": order, "shown": shown})
    return out


def fisher_less(a: int, b: int, c: int, d: int) -> float:
    """One-sided Fisher's exact test on [[a, b], [c, d]]: the chance of c or fewer under no difference, where c is
    the second row's count in the first column."""
    n1, n2, k = a + b, c + d, a + c
    total = math.comb(n1 + n2, k)
    return sum(math.comb(n2, x) * math.comb(n1, k - x) for x in range(0, c + 1) if k - x <= n1) / total


def verdict_study(*, ask: Callable[..., Optional[str]] = models.ask, rotations: int = ROTATIONS,
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    """Run the study and return its record (written by code; the model only picks offers)."""
    records = []
    misses = 0
    for t in trials(rotations):
        job, offers = SETS[t["set"]]
        ordered = [offers[i] for i in t["order"]]
        hosts = [o[0] for o in ordered]
        fmt = {"type": "json_schema", "schema": {"type": "object", "properties": {"choice": {"type": "string",
               "enum": hosts}}, "required": ["choice"], "additionalProperties": False}}
        text = ask("verdict-study", STUDY_SYSTEM, study_prompt(job, ordered, t["shown"]), max_tokens=300,
                   effort="low", output_format=fmt)
        choice = None
        if text:
            try:
                choice = json.loads(text).get("choice")
            except (ValueError, AttributeError):
                choice = None
        choice = choice if choice in hosts else None
        misses = 0 if choice else misses + 1
        records.append({**t, "choice": choice, "trap": choice == offers[0][0] if choice else None,
                        "place": hosts.index(choice) + 1 if choice else None})
        if misses >= 3:
            break                                         # the cap or the API stopped answering: stop spending
    counts = {}
    for shown, name in ((False, "without_verdict"), (True, "with_verdict")):
        answered = [r for r in records if r["shown"] is shown and r["choice"]]
        counts[name] = {"trials": sum(1 for r in records if r["shown"] is shown), "answered": len(answered),
                        "picked_the_offer_asking_more": sum(1 for r in answered if r["trap"])}
    places = {str(p): sum(1 for r in records if r["place"] == p) for p in (1, 2, 3)}
    a = counts["without_verdict"]["picked_the_offer_asking_more"]
    c = counts["with_verdict"]["picked_the_offer_asking_more"]
    b = counts["without_verdict"]["answered"] - a
    d = counts["with_verdict"]["answered"] - c
    p = round(fisher_less(a, b, c, d), 6) if (a + b) and (c + d) else None
    return {
        "kind": "agoranome.verdict-study", "format": 1, "made_at": (now or _now()).isoformat(),
        "model": models.model(),
        "question": "Does a verdict shown beside an offer move a buying model away from an offer that asks more "
                    "than it lists?",
        "method": [f"{len(SETS)} jobs, each with three offers Agoranome wrote (hosts under .example). In each, the "
                   "offer that lists the lowest price asked more than it lists; the others asked what they list.",
                   f"Each set shown in {rotations} orders, once without and once with the inspector's verdict beside "
                   f"every offer, a budget of ${STUDY_BUDGET} a request; the model answers with one host.",
                   "Fisher's exact test, one-sided: are fewer picks of that offer made with the verdict shown?",
                   "Every call is under the inspector's $20 monthly cap; the study stops after three calls in a "
                   "row give no answer."],
        "sets": [{"job": job, "offers": [{"host": h, "description": d, "listed_usd": li, "asked_usd": a_}
                                         for h, d, li, a_ in offers]} for job, offers in SETS],
        "trials": records, "counts": counts, "places": places, "fisher_one_sided_p": p,
        "reading": (f"Without the verdict the model picked the offer that asks more than it lists in {a} of "
                    f"{a + b} answered trials; with the verdict shown, in {c} of {c + d}."),
    }
