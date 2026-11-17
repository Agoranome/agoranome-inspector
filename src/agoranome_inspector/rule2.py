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

"""Rule sheet-2: price is judged on dollar options only.

Sheet-1 compares a listed and a live amount in each asset's own units. A seller who prices in dollars and quotes
XRP at the day's rate is above its listing whenever the index is a few days old, and on 16 Nov 2026 more than half of
the sheet's flagged listings were that drift. Sheet-2 judges price on the dollar options alone (USDC, by contract),
reports every other option's price verdict beside it as `floating`, never held against anyone, and names a quote
that only an empty request gets (an endpoint priced by its input) instead of counting it as an overcharge.

Sheet-1 stays as it was: a published rule is never changed, and every sheet names the rule it was judged by.
"""

from typing import Any, Dict, List, Optional, Tuple

from agoranome_inspector import networks
from agoranome_inspector.rule import _candidates, _compare, _option, _usable, answer

RULE = "sheet-2"

# The dollar options, by network and asset as compared: USDC on the ten networks whose contract is known. Frozen
# with the rule; a token added later is a new rule. Any other asset is floating (its dollar value moves, or it is
# not known to hold one) and its price is reported, not judged.
DOLLAR = frozenset({
    ("eip155:8453", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"),     # Base
    ("eip155:84532", "0x036cbd53842c5426634e7929541ec2318f3dcf7e"),    # Base Sepolia
    ("eip155:1", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"),        # Ethereum
    ("eip155:137", "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"),      # Polygon
    ("eip155:42161", "0xaf88d065e77c8cc2239327c5edb3a432268e5831"),    # Arbitrum
    ("eip155:10", "0x0b2c639c533813f4aa9d7837caf62653d097ff85"),       # Optimism
    ("eip155:43114", "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e"),    # Avalanche
    ("eip155:480", "0x79a02482a880bce3f13e09da970dc34db4cd24d1"),      # World Chain
    ("eip155:143", "0x754704bc059f8c67012fed69bc8a327a5aafb603"),      # Monad
    ("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),   # Solana
})

ANSWERS = ("payable", "unreadable_offer", "no_payment_asked", "gone", "http_4xx", "http_5xx", "unreachable",
           "declined", "not_asked", "other")
PRICES = ("as_listed", "below_listed", "above_listed", "listed_option_missing", "not_listed", "not_dollar",
          "input_priced", "varies")
FLOATING = ("as_listed", "below_listed", "above_listed", "listed_option_missing", "varies")
PAY_TOS = ("as_listed", "different", "listed_option_missing", "not_listed", "varies")
MAX_DIFFERS = 8
# seen.again.request when the confirming ask sent the example input the offer's own discovery block gives (see
# probe.example_request); without it the second ask was the same empty ask as the first.
SELLER_EXAMPLE = "seller_example"

METHOD = [
    "Who is on the sheet: every listing in Coinbase's x402 Bazaar index with 3 or more unique payers in 30 "
    "days on the day of the run (real demand). The index is the list of where to look; every verdict comes "
    "from the seller's own endpoint.",
    "How each listing is asked: an unpaid GET, then an empty JSON POST if the GET did not answer 402, from a "
    "public address, following no redirect. A listing that gives no payable offer is asked once more a few "
    "seconds later and the second answer is kept. A listing whose offer differs from its listing (a higher "
    "dollar price, a missing dollar option or another pay-to address) is asked once more a few seconds later, "
    "and both answers are kept (seen.again). When its dollar price is higher and its offer gives an example "
    "input in its discovery block (extensions.bazaar), the second ask sends that example (a query on a GET, a "
    "JSON body on a POST, at most 16,384 bytes) and seen.again.request says seller_example. Nothing is ever paid.",
    "answer: payable when the endpoint answered 402 with at least one payment option naming a network, an "
    "asset, an amount and a pay-to address (the x402 v2 PAYMENT-REQUIRED header or the v1 body); "
    "unreadable_offer for a 402 without one; no_payment_asked for a 2xx; gone for 404 or 410; http_4xx and "
    "http_5xx for other errors; unreachable when no HTTP answer came; declined when the URL is not public "
    "https, so it was not asked; not_asked when the run reached its per-host cap or time budget before "
    "asking it; other for anything else.",
    "Dollar options: an option is a dollar option when its network and asset are USDC on Base, Base Sepolia, "
    "Ethereum, Polygon, Arbitrum, Optimism, Avalanche, World Chain, Monad or Solana, by contract (the list is "
    "part of this rule). Every other option is floating: its dollar value moves, or is not known to this rule.",
    "Comparing one listed option: the live options on the same network, asset and scheme are its candidates "
    "(on the same network and asset, any scheme, when none has the same scheme). Its price is above_listed when "
    "any candidate asks more than every amount the listing states for that network, asset and scheme (a buyer "
    "agent may be asked to pay it), else as_listed when a candidate asks exactly the listed amount, else "
    "below_listed when the cheapest asks less. Its pay_to is as_listed when every candidate pays an address the "
    "listing states for that network, asset and scheme, different when any does not, not_listed when the "
    "option names no address.",
    "price of the row, from the listed dollar options only: not_listed when the listing states no usable price; "
    "not_dollar when it states no dollar option; listed_option_missing when no listed dollar option has a "
    "candidate; else above_listed when any compared dollar option is above_listed, else below_listed when any "
    "is below_listed, else as_listed.",
    "floating of the row: the same verdict from the listed floating options only, null when the listing states "
    "none. It is reported so the sheet hides nothing, and it is never held against the seller.",
    "pay_to of the row, from every compared listed option (an address does not drift): different when any is "
    "different, else as_listed when any names an address, else not_listed; listed_option_missing when no "
    "listed option has a candidate.",
    "Confirmation: when the endpoint was asked twice, a price, floating or pay_to that the two answers do not "
    "both give is varies, and is not held against the seller. When the second ask sent the offer's example "
    "input and the first answer's price was above_listed but the second's was as_listed or below_listed, the "
    "price is input_priced: the endpoint quotes by its input, and the higher quote to an empty request is a "
    "ceiling, not an overcharge.",
    "matches_listing: true when the price is as_listed or below_listed and the pay_to is as_listed; false when "
    "the price is above_listed or listed_option_missing or the pay_to is different; null otherwise (no payable "
    "offer, nothing in dollars listed to compare, input_priced, or a verdict that varies). A false says the "
    "live offer differs from the listing, which can also mean the listing is out of date; it is not a finding "
    "of bad faith.",
    "network: testnet_only when every live payable option is on a test network, else mainnet.",
    "asked: the live option compared with the first compared listed dollar option (listed options in sorted "
    "order), or with the first compared listed option when no dollar option is compared. differs: up to 8 "
    "compared listed options whose price is not as_listed or whose pay_to is different, dollar options first, "
    "each with its listed and live amount and address and whether it is a dollar option.",
    "Networks are compared as CAIP-2 ids (x402 v1 names are mapped; a reference longer than 32 characters is "
    "cut to 32), EVM addresses in lower case, other addresses as written, amounts as whole atomic units.",
    "Strict formats: a field that does not look like what it is is dropped, so that no seller can put a sentence "
    "into a signed sheet. A network must be a CAIP-2 id or an x402 v1 name; a scheme a short word; an asset or "
    "address hex after 0x, or letters, digits and . _ : - only, at most 80 characters; a pay-to on an EVM "
    "network a 20-byte address. An option missing a field is not payable. The example input sent is never "
    "kept.",
]


def is_dollar(option: Dict[str, Any]) -> bool:
    return (option.get("network"), option.get("asset")) in DOLLAR


def _sort_listed(o: Dict[str, Any]) -> Tuple:
    return (o["network"], o["asset"], o.get("scheme") or "", int(o["amount"]), o.get("pay_to") or "")


def _live_key(o: Dict[str, Any]) -> Tuple:
    return (int(o["amount"]), o["network"], o["asset"], o.get("scheme") or "", o["pay_to"])


def _price_of(compared: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> str:
    prices = {c["price"] for _, c in compared}
    return "above_listed" if "above_listed" in prices else "below_listed" if "below_listed" in prices \
        else "as_listed"


def _once(listed: List[Dict[str, Any]], seen: Dict[str, Any]) -> Dict[str, Any]:
    """The price, floating and pay-to verdicts from one payable answer."""
    live = sorted(_usable(seen.get("options") or [], need_pay_to=True), key=_live_key)
    stated = sorted(_usable(listed, need_pay_to=False), key=_sort_listed)
    if not stated:
        return {"price": "not_listed", "floating": None, "pay_to": "not_listed", "asked": _option(live[0]),
                "differs": []}

    def group(option: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [o for o in stated if (o["network"], o["asset"], o.get("scheme") or "")
                == (option["network"], option["asset"], option.get("scheme") or "")]

    compared = [(option, _compare(option, cands, group(option))) for option in stated
                for cands in [_candidates(option, live)] if cands]
    dollar = [(o, c) for o, c in compared if is_dollar(o)]
    floating_compared = [(o, c) for o, c in compared if not is_dollar(o)]
    if not any(is_dollar(o) for o in stated):
        price = "not_dollar"
    elif not dollar:
        price = "listed_option_missing"
    else:
        price = _price_of(dollar)
    if all(is_dollar(o) for o in stated):
        floating: Optional[str] = None
    elif not floating_compared:
        floating = "listed_option_missing"
    else:
        floating = _price_of(floating_compared)
    if not compared:
        pay_to = "listed_option_missing"
    else:
        pays = {c["pay_to"] for _, c in compared}
        pay_to = "different" if "different" in pays else "as_listed" if "as_listed" in pays else "not_listed"
    first = (dollar or compared or [(None, {"asked": live[0]})])[0][1]["asked"]
    differs = [{"network": o["network"], "asset": o["asset"], "scheme": o.get("scheme"), "dollar": is_dollar(o),
                "listed_amount": o["amount"], "listed_pay_to": o.get("pay_to"),
                "asked_amount": c["asked"]["amount"], "asked_pay_to": c["asked"]["pay_to"],
                "price": c["price"], "pay_to": c["pay_to"]}
               for o, c in dollar + floating_compared
               if c["price"] != "as_listed" or c["pay_to"] == "different"][:MAX_DIFFERS]
    return {"price": price, "floating": floating, "pay_to": pay_to, "asked": _option(first), "differs": differs}


def needs_confirmation(verdict: Dict[str, Any]) -> bool:
    """Whether a first answer differs from the listing in a way that counts against the seller."""
    return verdict.get("answer") == "payable" and (
        verdict.get("price") in ("above_listed", "listed_option_missing") or verdict.get("pay_to") == "different")


def wants_example(verdict: Dict[str, Any]) -> bool:
    """Whether the confirming ask should send the offer's example input: the first dollar price was higher than
    listed, which an endpoint priced by its input gives to an empty request."""
    return verdict.get("answer") == "payable" and verdict.get("price") == "above_listed"


def _confirmed(first: Optional[str], second: Optional[str]) -> Optional[str]:
    return first if second == first else "varies"


def judge(listed: List[Dict[str, Any]], seen: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The verdict on one row under sheet-2."""
    said = answer(seen)
    verdict: Dict[str, Any] = {"answer": said, "price": None, "floating": None, "pay_to": None,
                               "matches_listing": None, "network": None, "asked": None, "differs": []}
    if said != "payable":
        return verdict
    live = _usable(seen.get("options") or [], need_pay_to=True)
    first = _once(listed, seen)
    price, floating, pay_to = first["price"], first["floating"], first["pay_to"]
    again = seen.get("again")
    if again is not None:
        second = _once(listed, again) if answer(again) == "payable" else \
            {"price": None, "floating": None, "pay_to": None}
        if (price == "above_listed" and again.get("request") == SELLER_EXAMPLE
                and second["price"] in ("as_listed", "below_listed")):
            price = "input_priced"
        else:
            price = _confirmed(price, second["price"])
        floating = floating if floating is None else _confirmed(floating, second["floating"])
        pay_to = _confirmed(pay_to, second["pay_to"])
    if price in ("above_listed", "listed_option_missing") or pay_to == "different":
        matches: Optional[bool] = False
    elif price in ("as_listed", "below_listed") and pay_to == "as_listed":
        matches = True
    else:
        matches = None
    verdict.update(price=price, floating=floating, pay_to=pay_to, matches_listing=matches,
                   network="testnet_only" if all(networks.is_testnet(o["network"]) for o in live) else "mainnet",
                   asked=first["asked"], differs=first["differs"])
    return verdict
