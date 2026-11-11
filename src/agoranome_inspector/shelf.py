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

"""The shelf report card: a grade for each shelf machines shop from, by the published rule `shelf-1`.

A shelf is where a buying agent finds paid endpoints: Coinbase's x402 Bazaar, the same index as AWS Bedrock
AgentCore's agents reach it, the MPP catalog, and Skyfire's directory. The sheets grade sellers; this card grades
the shelves, on what decides whether a market is fair to a buyer that cannot look behind it:

  open      Can anyone read the whole shelf, without an account?
  rank      Is the rule that orders a search published, with nothing a seller can pay for?
  matches   Do the shelf's listings match what the sellers ask when asked? (measured, from the newest sheet)
  delivery  Does the shelf show whether a seller delivers what it was paid for?
  dispute   Can a buyer dispute a charge through the shelf?

Each answer is yes (2 points), partly (1), no or unknown (0). The grade is A at 8 points or more, B at 6, C at 4,
D below. Four answers are facts read from the shelves' own documents, each with its source and the day it was read;
`matches` is measured. A shelf that thinks a fact is wrong can point to its documents: the correction is a new
entry in the book, and the card is graded again. Every input is in the shelf entry, so the verifier recomputes the
card from the entry and the sheets the book already holds.
"""

from typing import Any, Dict, List, Optional

from agoranome_inspector import sheet as sheet_lib

RULE = "shelf-1"
QUESTIONS = ("open", "rank", "matches", "delivery", "dispute")
POINTS = {"yes": 2, "partly": 1, "no": 0, "unknown": 0}
READ = "2026-11-11"
COINBASE_DOCS = "https://docs.cdp.coinbase.com/x402/seller/get-discovered"
AGENTCORE_DOCS = "https://docs.aws.amazon.com/bedrock-agentcore/"
MPP_DOCS = "https://mpp.dev"
SKYFIRE_DOCS = "https://docs.skyfire.xyz"
# matches: at least this share of payable offers asking no more than listed, to the same pay-to, is "yes"; at least
# the second is "partly".
MATCH_YES, MATCH_PARTLY = 0.95, 0.80

# What each shelf's own documents said when read. A fact is a short plain statement of what was read, never a
# judgement; the answer is the rule applied to it.
FACTS: Dict[str, Dict[str, Any]] = {
    "bazaar": {
        "name": "Coinbase x402 Bazaar", "market": "x402", "url": COINBASE_DOCS,
        "facts": {
            "open": {"answer": "yes", "read": READ, "source": COINBASE_DOCS,
                     "says": "The discovery index and its search are public; no key is needed."},
            "rank": {"answer": "partly", "read": READ, "source": COINBASE_DOCS,
                     "says": "Search ranks by 30 days of buyers and volume, recency and the listing's text; a "
                             "hand-picked curated tier ranks first and the choice remains editorial. Buyers and "
                             "volume can be bought by a seller paying its own endpoint."},
            "delivery": {"answer": "no", "read": READ, "source": COINBASE_DOCS,
                         "says": "A listing shows its price and demand. Nothing on it says whether the seller "
                                 "delivered what was paid for."},
            "dispute": {"answer": "no", "read": READ, "source": COINBASE_DOCS,
                        "says": "No way to dispute a charge was found in the seller or discovery documents."},
        },
    },
    "agentcore": {
        "name": "AWS Bedrock AgentCore (its Bazaar gateway)", "market": "x402", "url": AGENTCORE_DOCS,
        "facts": {
            "open": {"answer": "partly", "read": READ, "source": AGENTCORE_DOCS,
                     "says": "Agents reach Coinbase's Bazaar through a built-in gateway target; a search gives at "
                             "most 20 results and no next page."},
            "rank": {"answer": "partly", "read": READ, "source": COINBASE_DOCS,
                     "says": "The order is the Bazaar's: buyers and volume, recency and text, with an editorial "
                             "curated tier first."},
            "delivery": {"answer": "no", "read": READ, "source": AGENTCORE_DOCS,
                         "says": "Nothing shown says whether a seller delivered. A spending cap per session is "
                                 "enforced outside the model, which limits a loss but does not show delivery."},
            "dispute": {"answer": "unknown", "read": READ, "source": AGENTCORE_DOCS,
                        "says": "AWS's terms on disputing an x402 payment were not found."},
        },
    },
    "mpp": {
        "name": "MPP service catalog", "market": "mpp", "url": MPP_DOCS,
        "facts": {
            "open": {"answer": "yes", "read": READ, "source": "https://mpp.dev/api/services",
                     "says": "The catalog is public JSON, with a read-only MCP server beside it."},
            "rank": {"answer": "no", "read": READ, "source": MPP_DOCS,
                     "says": "The catalog is curated; no rule for who is in it or in what order was found. Its "
                             "documents call discovery advisory and the live 402 authoritative."},
            "delivery": {"answer": "no", "read": READ, "source": MPP_DOCS,
                         "says": "No delivery or demand figures are on the catalog."},
            "dispute": {"answer": "unknown", "read": READ, "source": MPP_DOCS,
                        "says": "Payment methods include cards through Stripe; whether a buyer agent can dispute "
                                "a charge through the catalog was not found."},
        },
    },
    "skyfire": {
        "name": "Skyfire directory", "market": "skyfire", "url": SKYFIRE_DOCS,
        "facts": {
            "open": {"answer": "no", "read": READ, "source": SKYFIRE_DOCS,
                     "says": "The directory is reached in Skyfire's dashboard, with an account."},
            "rank": {"answer": "unknown", "read": READ, "source": SKYFIRE_DOCS,
                     "says": "Sellers are reviewed in about 48 hours before they are shown; no ordering rule was "
                             "found."},
            "delivery": {"answer": "unknown", "read": READ, "source": SKYFIRE_DOCS,
                         "says": "A Verified tag marks subscribed sellers that passed an identity check; nothing "
                                 "found says whether a seller delivers."},
            "dispute": {"answer": "unknown", "read": READ, "source": SKYFIRE_DOCS,
                        "says": "The seller charges the buyer's token itself; a dispute path was not found."},
        },
    },
}


def measured_match(sheet_body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """`matches` from a sheet's book entry: the share of payable offers that asked no more than listed, and (on x402)
    paid the listed address."""
    if not sheet_body:
        return {"answer": "unknown", "says": "No sheet of this market is in the book yet.", "sheet": None}
    s = sheet_body.get("summary") or {}
    payable = int((s.get("answer") or {}).get("payable", 0))
    price, pay_to = s.get("price") or {}, s.get("pay_to") or {}
    judged = payable - int(price.get("not_listed", 0)) - int(price.get("varies", 0))
    held = int(price.get("above_listed", 0)) + int(price.get("listed_option_missing", 0)) \
        + int(pay_to.get("different", 0))
    if judged <= 0:
        return {"answer": "unknown", "says": "No payable offer could be judged on price.",
                "sheet": sheet_body.get("id"), "payable": payable}
    share = max(0.0, (judged - held) / judged)
    answer = "yes" if share >= MATCH_YES else "partly" if share >= MATCH_PARTLY else "no"
    return {"answer": answer, "sheet": sheet_body.get("id"), "payable": payable, "judged": judged,
            "matched": judged - held, "share": f"{share:.3f}",
            "says": f"{judged - held:,} of {judged:,} payable offers judged on price asked no more than listed"
                    + (" and named the listed pay-to." if sheet_body.get("market", "x402") == "x402" else ".")}


def grade(points: int) -> str:
    return "A" if points >= 8 else "B" if points >= 6 else "C" if points >= 4 else "D"


def card(facts: Dict[str, Dict[str, Any]], sheets: Dict[str, Optional[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Each shelf's card from the facts and the newest sheet entry body of each market."""
    out = []
    for key in sorted(facts):
        shelf = facts[key]
        answers: Dict[str, Dict[str, Any]] = {}
        for q in QUESTIONS:
            if q == "matches":
                answers[q] = measured_match(sheets.get(shelf["market"]))
            else:
                fact = (shelf.get("facts") or {}).get(q) or {"answer": "unknown", "says": "Not read."}
                answers[q] = {k: fact.get(k) for k in ("answer", "says", "source", "read")}
        points = sum(POINTS.get(a["answer"], 0) for a in answers.values())
        out.append({"shelf": key, "name": shelf["name"], "market": shelf["market"], "url": shelf.get("url"),
                    "answers": answers, "points": points, "of": 2 * len(QUESTIONS), "grade": grade(points)})
    return out


def newest_sheets(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    newest: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        if e.get("kind") == "sheet":
            newest[sheet_lib.market_of(e["body"])] = e
    return newest


def shelf_body(entries: List[Dict[str, Any]], facts: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    facts = FACTS if facts is None else facts
    newest = newest_sheets(entries)
    return {"rule": RULE, "facts": facts,
            "sheets": {m: {"seq": e["seq"], "id": e["body"].get("id")} for m, e in sorted(newest.items())},
            "shelves": card(facts, {m: e["body"] for m, e in newest.items()})}


def check(body: Dict[str, Any], entries: List[Dict[str, Any]]) -> List[str]:
    """Recompute a shelf entry's card from its facts and the sheet entries it names."""
    if body.get("rule") != RULE:
        return [f"unknown shelf rule {body.get('rule')!r}"]
    by_seq = {e["seq"]: e for e in entries}
    sheets = {}
    for market, ref in (body.get("sheets") or {}).items():
        entry = by_seq.get(ref.get("seq"))
        if entry is None or entry.get("kind") != "sheet" or entry["body"].get("id") != ref.get("id"):
            return [f"the shelf card names sheet {ref.get('id')} at entry {ref.get('seq')}, which the book lacks"]
        sheets[market] = entry["body"]
    if card(body.get("facts") or {}, sheets) != body.get("shelves"):
        return ["the shelf card does not follow from its facts and sheets"]
    return []
