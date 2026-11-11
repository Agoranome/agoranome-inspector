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

"""The MPP sheet's rule, `mpp-1`: a row's verdict as a pure function of what the MPP catalog lists for an endpoint
and what the endpoint's unpaid 402 challenges ask.

It compares the way x402's `sheet-1` does (the same comparison code), with an MPP option's payment method in the
place of the network, its currency in the place of the asset, its intent in the place of the scheme and its
recipient in the place of the pay-to address. Two differences: the catalog names no recipient, so the recipient is
never held against anyone (`pay_to` is `not_listed`, and a matching price is enough for `matches_listing`); and a
listing that marks its price dynamic states no price to compare (`not_listed`).
"""

from typing import Any, Dict, List, Optional

from agoranome_inspector import rule as x402

RULE = "mpp-1"

METHOD = [
    "Who is on the sheet: every endpoint with a payment in the public MPP catalog (https://mpp.dev/api/services) "
    "on the day of the run, except paths that need parameters filled in. The catalog states no demand, so no "
    "demand is claimed. Every verdict comes from the endpoint's own answer.",
    "How each endpoint is asked: with the HTTP method the catalog lists (GET or POST; other methods are not "
    "asked), from a public address, following no redirect, with the example request the seller's own OpenAPI "
    "document (/openapi.json on the endpoint's host) gives for that path and method: its example body and its "
    "required query parameters' examples, or values built from the schema's own examples, defaults and enums "
    "(request: seller_example). With no such example it is asked with no parameters and, for POST, an empty "
    "JSON body (request: empty). The example is sent, not published. One that gives no payable "
    "challenge is asked once more a few seconds later and the second answer is kept. One whose challenge differs "
    "from its listing in a way that would count against the seller (a higher price, a missing method) is asked "
    "once more a few seconds later, and both answers are kept (seen.again). Nothing is ever paid.",
    "answer: payable when the endpoint answered 402 with at least one WWW-Authenticate Payment challenge whose "
    "request names an amount, a currency and a recipient; unreadable_offer for a 402 without one; the other "
    "answers as in sheet-1 (a 401 asking for a token first is http_4xx), except that a 400 or 422 is wants_input: "
    "the endpoint checks the request before it quotes a price, as one whose price depends on the request must, "
    "and the request the inspector could send did not satisfy it. wants_input is not a failing and is not "
    "judged.",
    "Comparing one listed payment: the live challenges with the same method, currency and intent are its "
    "candidates (same method and currency, any intent, when none has the same intent). Its price is as_listed "
    "when a candidate asks exactly the listed amount, below_listed when the cheapest asks less, above_listed "
    "when every candidate asks more. A listing marked dynamic states no price (not_listed).",
    "price of the row: listed_option_missing when the listed payment has no candidate; not_listed when the "
    "listing states no usable price; else above_listed, below_listed or as_listed.",
    "pay_to: not_listed, because the catalog names no recipient; the recipient each challenge names is kept in "
    "the row and its changes are in the change log.",
    "Confirmation: when the endpoint was asked twice, a price that the two answers do not both give is varies, "
    "and is not held against the seller.",
    "matches_listing: true when the price is as_listed or below_listed; false when the price is above_listed or "
    "listed_option_missing; null otherwise. A false says the live challenge differs from the catalog, which can "
    "also mean the catalog is out of date; it is not a finding of bad faith.",
    "Comparing: methods and intents in lower case, currencies as ISO codes in lower case or addresses (EVM hex "
    "in lower case, others as written), amounts as whole base units as the catalog and the challenge state them.",
]

TO_X402 = {"method": "network", "currency": "asset", "intent": "scheme", "amount": "amount", "recipient": "pay_to"}
FROM_X402 = {"network": "method", "asset": "currency", "scheme": "intent", "pay_to": "recipient",
             "listed_pay_to": "listed_recipient", "asked_pay_to": "asked_recipient"}


def _to_x402(option: Dict[str, Any]) -> Dict[str, Any]:
    return {x: option.get(m) for m, x in TO_X402.items()}


def _from_x402(found: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if found is None:
        return None
    return {FROM_X402.get(k, k): v for k, v in found.items()}


def _seen_as_x402(seen: Dict[str, Any]) -> Dict[str, Any]:
    return {**seen, "options": [_to_x402(o) for o in seen.get("options") or []]}


WANTS_INPUT = (400, 422)


def answer(seen: Optional[Dict[str, Any]]) -> str:
    said = x402.answer(None if seen is None else _seen_as_x402(seen))
    if said == "http_4xx" and (seen or {}).get("status") in WANTS_INPUT:
        return "wants_input"
    return said


def needs_confirmation(verdict: Dict[str, Any]) -> bool:
    return x402.needs_confirmation(verdict)


def _once(listed: List[Dict[str, Any]], seen: Dict[str, Any]) -> Dict[str, Any]:
    found = x402._once([_to_x402(o) for o in listed], _seen_as_x402(seen))
    if found["pay_to"] == "listed_option_missing":
        pay_to = "listed_option_missing"
    else:
        pay_to = "not_listed"
    differs = [_from_x402({**d, "pay_to": pay_to}) for d in found["differs"] if d["price"] != "as_listed"]
    return {"price": found["price"], "pay_to": pay_to, "asked": _from_x402(found["asked"]), "differs": differs}


def judge(listed: List[Dict[str, Any]], seen: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The verdict on one row under mpp-1."""
    said = answer(seen)
    verdict: Dict[str, Any] = {"answer": said, "price": None, "pay_to": None, "matches_listing": None,
                               "network": None, "asked": None, "differs": []}
    if said != "payable":
        return verdict
    first = _once(listed, seen)
    price, pay_to = first["price"], first["pay_to"]
    again = seen.get("again")
    if again is not None:
        second = _once(listed, again) if answer(again) == "payable" else {"price": None, "pay_to": None}
        price = price if second["price"] == price else "varies"
        pay_to = pay_to if second["pay_to"] == pay_to else "varies"
    if price in ("above_listed", "listed_option_missing"):
        matches: Optional[bool] = False
    elif price in ("as_listed", "below_listed"):
        matches = True
    else:
        matches = None
    verdict.update(price=price, pay_to=pay_to, matches_listing=matches, asked=first["asked"],
                   differs=first["differs"])
    return verdict
