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
PRICES = ("as_listed", "below_listed", "above_listed", "listed_option_missing", "not_listed")
PAY_TOS = ("as_listed", "different", "listed_option_missing", "not_listed")

METHOD = [
    "Who is on the sheet: every listing in Coinbase's x402 Bazaar index with 3 or more unique payers in 30 "
    "days on the day of the run (real demand). The index is the list of where to look; every verdict comes "
    "from the seller's own endpoint.",
    "How each listing is asked: an unpaid GET, then an empty JSON POST if the GET did not answer 402, from a "
    "public address, following no redirect. A listing that gives no payable offer is asked once more a few "
    "seconds later and the second answer is kept. Nothing is ever paid.",
    "answer: payable when the endpoint answered 402 with at least one payment option naming a network, an "
    "asset, an amount and a pay-to address (the x402 v2 PAYMENT-REQUIRED header or the v1 body); "
    "unreadable_offer for a 402 without one; no_payment_asked for a 2xx; gone for 404 or 410; http_4xx and "
    "http_5xx for other errors; unreachable when no HTTP answer came; declined when the URL is not public "
    "https, so it was not asked; not_asked when the run reached its per-host cap or time budget before "
    "asking it; other for anything else.",
    "price: of the listing's options, those offered live on the same network and asset are compared, each "
    "with the cheapest live option on that network and asset. above_listed when any asks more than listed; "
    "else below_listed when any asks less; else as_listed. listed_option_missing when no listed option is "
    "offered live on its network and asset; not_listed when the listing states no usable price.",
    "pay_to: as_listed when every compared listed option with a pay-to address is offered live paying that "
    "address; different when any is not; listed_option_missing and not_listed as for price.",
    "network: testnet_only when every live payable option is on a test network, else mainnet.",
    "kept: true when the price is as_listed or below_listed and the pay_to is as_listed; false when the price "
    "is above_listed or listed_option_missing or the pay_to is different; null when the endpoint gave no "
    "payable offer, or the listing states no price or no pay-to address to compare.",
    "asked: the live option the comparison used (the first compared listed option's cheapest match), or the "
    "first live option when none could be compared.",
    "Networks are compared as CAIP-2 ids (x402 v1 names are mapped), EVM addresses in lower case, Solana "
    "addresses as written, amounts as whole atomic units.",
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
    if not isinstance(status, int):
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


def judge(listed: List[Dict[str, Any]], seen: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The verdict on one row under sheet-1."""
    said = answer(seen)
    verdict: Dict[str, Any] = {"answer": said, "price": None, "pay_to": None, "network": None, "kept": None,
                               "asked": None}
    if said != "payable":
        return verdict
    live = _usable(seen.get("options") or [], need_pay_to=True)
    live.sort(key=lambda o: (int(o["amount"]), o["network"], o["asset"], o["pay_to"]))
    verdict["network"] = "testnet_only" if all(networks.is_testnet(o["network"]) for o in live) else "mainnet"
    stated = _usable(listed, need_pay_to=False)
    if not stated:
        verdict.update(price="not_listed", pay_to="not_listed", asked=_option(live[0]))
        return verdict
    matches = []
    for option in stated:
        same = [o for o in live if o["network"] == option["network"] and o["asset"] == option["asset"]]
        if same:
            matches.append((option, same))
    if not matches:
        verdict.update(price="listed_option_missing", pay_to="listed_option_missing", kept=False,
                       asked=_option(live[0]))
        return verdict
    above = any(int(same[0]["amount"]) > int(option["amount"]) for option, same in matches)
    below = any(int(same[0]["amount"]) < int(option["amount"]) for option, same in matches)
    price = "above_listed" if above else "below_listed" if below else "as_listed"
    with_address = [(option, same) for option, same in matches if option.get("pay_to")]
    if not with_address:
        pay_to = "not_listed"
    elif all(any(o["pay_to"] == option["pay_to"] for o in same) for option, same in with_address):
        pay_to = "as_listed"
    else:
        pay_to = "different"
    if price == "above_listed" or pay_to == "different":
        kept: Optional[bool] = False
    elif pay_to == "as_listed":
        kept = True
    else:
        kept = None
    verdict.update(price=price, pay_to=pay_to, kept=kept, asked=_option(matches[0][1][0]))
    return verdict


RULES = {RULE: judge}
