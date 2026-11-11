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

"""The sheet's rule: what a row's verdict is, as a pure function of what the listing states and what the
endpoint answered. Anyone can run it again on a published row and must get the same verdict.

A rule never changes once a sheet is published under it. A new rule gets a new name, and each sheet names the
rule it was judged by, so an old sheet always verifies under its own rule.
"""

from typing import Any, Dict, List, Optional

from agoranome_inspector import networks

RULE = "sheet-1"

ANSWERS = ("payable", "unreadable_offer", "no_payment_asked", "gone", "http_4xx", "http_5xx", "unreachable",
           "declined", "not_asked", "other")
PRICES = ("as_listed", "below_listed", "above_listed", "listed_option_missing", "not_listed", "varies")
PAY_TOS = ("as_listed", "different", "listed_option_missing", "not_listed", "varies")
MAX_DIFFERS = 8

METHOD = [
    "Who is on the sheet: every listing in Coinbase's x402 Bazaar index with 3 or more unique payers in 30 "
    "days on the day of the run (real demand). The index is the list of where to look; every verdict comes "
    "from the seller's own endpoint.",
    "How each listing is asked: an unpaid GET, then an empty JSON POST if the GET did not answer 402, from a "
    "public address, following no redirect. A listing that gives no payable offer is asked once more a few "
    "seconds later and the second answer is kept. A listing whose offer differs from its listing (a higher "
    "price, a missing option or another pay-to address) is asked once more a few seconds later, and both "
    "answers are kept (seen.again). Nothing is ever paid.",
    "answer: payable when the endpoint answered 402 with at least one payment option naming a network, an "
    "asset, an amount and a pay-to address (the x402 v2 PAYMENT-REQUIRED header or the v1 body); "
    "unreadable_offer for a 402 without one; no_payment_asked for a 2xx; gone for 404 or 410; http_4xx and "
    "http_5xx for other errors; unreachable when no HTTP answer came; declined when the URL is not public "
    "https, so it was not asked; not_asked when the run reached its per-host cap or time budget before "
    "asking it; other for anything else.",
    "Comparing one listed option: the live options on the same network, asset and scheme are its candidates "
    "(on the same network and asset, any scheme, when none has the same scheme). Its price is as_listed when "
    "a candidate asks exactly the listed amount, below_listed when the cheapest asks less, above_listed when "
    "every candidate asks more. Its pay_to is as_listed when a candidate pays the listed address, different "
    "when none does, not_listed when the option names no address.",
    "price of the row: listed_option_missing when no listed option has a candidate; not_listed when the "
    "listing states no usable price; else above_listed when any compared option is above_listed, else "
    "below_listed when any is below_listed, else as_listed.",
    "pay_to of the row: different when any compared option is different, else as_listed when any names an "
    "address, else not_listed (listed_option_missing as for price).",
    "Confirmation: when the endpoint was asked twice, a price or pay_to that the two answers do not both give "
    "is varies, and is not held against the seller.",
    "matches_listing: true when the price is as_listed or below_listed and the pay_to is as_listed; false when "
    "the price is above_listed or listed_option_missing or the pay_to is different; null otherwise (no payable "
    "offer, nothing listed to compare, or a verdict that varies). A false says the live offer differs from "
    "the listing, which can also mean the listing is out of date; it is not a finding of bad faith.",
    "network: testnet_only when every live payable option is on a test network, else mainnet.",
    "asked: the live option compared with the first compared listed option (listed options in sorted order). "
    "differs: up to 8 compared listed options whose price is not as_listed or whose pay_to is different, each "
    "with its listed and live amount and address.",
    "Networks are compared as CAIP-2 ids (x402 v1 names are mapped; a reference longer than 32 characters is "
    "cut to 32), EVM addresses in lower case, other addresses as written, amounts as whole atomic units.",
    "Strict formats: a field that does not look like what it is is dropped, so that no seller can put a sentence "
    "into a signed sheet. A network must be a CAIP-2 id or an x402 v1 name; a scheme a short word; an asset or "
    "address hex after 0x, or letters, digits and . _ : - only, at most 80 characters; a pay-to on an EVM "
    "network a 20-byte address. An option missing a field is not payable.",
]


def _usable(options: List[Dict[str, Any]], need_pay_to: bool) -> List[Dict[str, Any]]:
    return [o for o in options or []
            if o.get("network") and o.get("asset") and o.get("amount") is not None
            and (o.get("pay_to") or not need_pay_to)]


def answer(seen: Optional[Dict[str, Any]]) -> str:
    if seen is None:
        return "not_asked"
    if seen.get("error") == "refused":
        return "declined"
    if seen.get("error"):
        return "unreachable"
    status = seen.get("status")
    if not isinstance(status, int) or isinstance(status, bool):
        return "other"
    if status == 402:
        return "payable" if _usable(seen.get("options") or [], need_pay_to=True) else "unreadable_offer"
    if 200 <= status < 300:
        return "no_payment_asked"
    if status in (404, 410):
        return "gone"
    if 400 <= status < 500:
        return "http_4xx"
    if 500 <= status < 600:
        return "http_5xx"
    return "other"


def _option(o: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return {k: o.get(k) for k in ("network", "asset", "amount", "pay_to")} if o else None


def _key(o: Dict[str, Any]) -> tuple:
    return (int(o["amount"]), o["network"], o["asset"], o.get("scheme") or "", o["pay_to"])


def _candidates(option: Dict[str, Any], live: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    same = [o for o in live if o["network"] == option["network"] and o["asset"] == option["asset"]]
    strict = [o for o in same if option.get("scheme") and o.get("scheme") == option["scheme"]]
    return strict or same


def _compare(option: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    amount = int(option["amount"])
    at = [c for c in candidates if int(c["amount"]) == amount]
    if at:
        price = "as_listed"
    else:
        cheapest = int(candidates[0]["amount"])
        price = "below_listed" if cheapest < amount else "above_listed"
        at = [c for c in candidates if int(c["amount"]) == cheapest]
    if not option.get("pay_to"):
        pay_to = "not_listed"
    elif any(c["pay_to"] == option["pay_to"] for c in candidates):
        pay_to = "as_listed"
    else:
        pay_to = "different"
    asked = next((c for c in at if c["pay_to"] == option.get("pay_to")), at[0])
    return {"price": price, "pay_to": pay_to, "asked": asked}


def _once(listed: List[Dict[str, Any]], seen: Dict[str, Any]) -> Dict[str, Any]:
    """The price and pay-to verdicts from one payable answer."""
    live = sorted(_usable(seen.get("options") or [], need_pay_to=True), key=_key)
    stated = sorted(_usable(listed, need_pay_to=False),
                    key=lambda o: (o["network"], o["asset"], o.get("scheme") or "", int(o["amount"]),
                                   o.get("pay_to") or ""))
    if not stated:
        return {"price": "not_listed", "pay_to": "not_listed", "asked": _option(live[0]), "differs": []}
    compared = [(option, _compare(option, cands)) for option in stated for cands in [_candidates(option, live)]
                if cands]
    if not compared:
        return {"price": "listed_option_missing", "pay_to": "listed_option_missing", "asked": _option(live[0]),
                "differs": []}
    prices = {c["price"] for _, c in compared}
    price = "above_listed" if "above_listed" in prices else "below_listed" if "below_listed" in prices \
        else "as_listed"
    pays = {c["pay_to"] for _, c in compared}
    pay_to = "different" if "different" in pays else "as_listed" if "as_listed" in pays else "not_listed"
    differs = [{"network": o["network"], "asset": o["asset"], "scheme": o.get("scheme"),
                "listed_amount": o["amount"], "listed_pay_to": o.get("pay_to"),
                "asked_amount": c["asked"]["amount"], "asked_pay_to": c["asked"]["pay_to"],
                "price": c["price"], "pay_to": c["pay_to"]}
               for o, c in compared if c["price"] != "as_listed" or c["pay_to"] == "different"][:MAX_DIFFERS]
    return {"price": price, "pay_to": pay_to, "asked": _option(compared[0][1]["asked"]), "differs": differs}


def needs_confirmation(verdict: Dict[str, Any]) -> bool:
    """Whether a first answer differs from the listing in a way that counts against the seller."""
    return verdict.get("answer") == "payable" and (
        verdict.get("price") in ("above_listed", "listed_option_missing") or verdict.get("pay_to") == "different")


def judge(listed: List[Dict[str, Any]], seen: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The verdict on one row under sheet-1."""
    said = answer(seen)
    verdict: Dict[str, Any] = {"answer": said, "price": None, "pay_to": None, "matches_listing": None,
                               "network": None, "asked": None, "differs": []}
    if said != "payable":
        return verdict
    live = _usable(seen.get("options") or [], need_pay_to=True)
    first = _once(listed, seen)
    price, pay_to = first["price"], first["pay_to"]
    again = seen.get("again")
    if again is not None:
        second = _once(listed, again) if answer(again) == "payable" else {"price": None, "pay_to": None}
        price = price if second["price"] == price else "varies"
        pay_to = pay_to if second["pay_to"] == pay_to else "varies"
    if price in ("above_listed", "listed_option_missing") or pay_to == "different":
        matches: Optional[bool] = False
    elif price in ("as_listed", "below_listed") and pay_to == "as_listed":
        matches = True
    else:
        matches = None
    verdict.update(price=price, pay_to=pay_to, matches_listing=matches,
                   network="testnet_only" if all(networks.is_testnet(o["network"]) for o in live) else "mainnet",
                   asked=first["asked"], differs=first["differs"])
    return verdict


RULES = {RULE: judge}
