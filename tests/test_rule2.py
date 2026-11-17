"""Rule sheet-2: price judged on dollar options only, the rest reported as floating, input-priced quotes named."""

import base64
import json

import httpx

from agoranome_inspector import rule
from agoranome_inspector.probe import SELLER_EXAMPLE, ask_with, example_request, observe
from agoranome_inspector.rule2 import DOLLAR, is_dollar, judge, needs_confirmation, wants_example

USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
WORLD_USDC = "0x79a02482a880bce3f13e09da970dc34db4cd24d1"
EURC = "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42"
A = "0x1111111111111111111111111111111111111111"
B = "0x2222222222222222222222222222222222222222"
XRP_A = "rA1111111111111111111111111111111"
XRP_B = "rB2222222222222222222222222222222"


def usdc(amount, pay_to=A, network="eip155:8453", asset=USDC, scheme="exact"):
    return {"scheme": scheme, "network": network, "asset": asset, "amount": amount, "pay_to": pay_to}


def xrp(amount, pay_to=XRP_A):
    return {"scheme": "exact", "network": "xrpl:0", "asset": "XRP", "amount": amount, "pay_to": pay_to}


def seen(*options, again=None, status=402):
    found = {"status": status, "options": list(options), "error": None}
    if again is not None:
        found["again"] = again
    return found


def test_the_ten_dollar_options_are_usdc_by_contract():
    assert len(DOLLAR) == 10
    assert is_dollar(usdc("1")) and is_dollar(usdc("1", network="eip155:480", asset=WORLD_USDC))
    assert not is_dollar(xrp("1")) and not is_dollar(usdc("1", asset=EURC))
    assert not is_dollar(usdc("1", network="eip155:137"))          # Base's contract on another network


def test_xrp_drift_is_floating_and_not_held_against_the_seller():
    """The 16 Nov case: dollars exactly as listed, XRP a little higher at the day's rate."""
    listed = [usdc("10000"), xrp("2077")]
    v = judge(listed, seen(usdc("10000"), xrp("2105")))
    assert (v["price"], v["floating"], v["pay_to"], v["matches_listing"]) == (
        "as_listed", "above_listed", "as_listed", True)
    assert rule.judge(listed, seen(usdc("10000"), xrp("2105")))["matches_listing"] is False   # sheet-1 flagged it
    assert v["differs"] == [{"network": "xrpl:0", "asset": "XRP", "scheme": "exact", "dollar": False,
                             "listed_amount": "2077", "listed_pay_to": XRP_A, "asked_amount": "2105",
                             "asked_pay_to": XRP_A, "price": "above_listed", "pay_to": "as_listed"}]
    assert v["asked"]["asset"] == USDC                              # the dollar option is the one shown


def test_a_higher_dollar_price_still_differs():
    v = judge([usdc("10000"), xrp("2077")], seen(usdc("12000"), xrp("2077")))
    assert (v["price"], v["floating"], v["matches_listing"]) == ("above_listed", "as_listed", False)
    assert v["differs"][0]["dollar"] is True


def test_an_address_does_not_drift_so_a_floating_payee_still_counts():
    v = judge([usdc("10000"), xrp("2077")], seen(usdc("10000"), xrp("2077", pay_to=XRP_B)))
    assert (v["price"], v["pay_to"], v["matches_listing"]) == ("as_listed", "different", False)


def test_a_listing_with_no_dollar_option_is_not_judged_on_price():
    v = judge([xrp("2077")], seen(xrp("2105")))
    assert (v["price"], v["floating"], v["pay_to"], v["matches_listing"]) == (
        "not_dollar", "above_listed", "as_listed", None)


def test_a_dollar_option_gone_from_the_offer_is_missing():
    v = judge([usdc("10000"), xrp("2077")], seen(xrp("2077")))
    assert (v["price"], v["floating"], v["matches_listing"]) == ("listed_option_missing", "as_listed", False)
    assert needs_confirmation(v)


def test_dollars_only_listing_has_no_floating_verdict():
    v = judge([usdc("5000")], seen(usdc("5000")))
    assert v["floating"] is None and v["matches_listing"] is True


def test_a_quote_only_an_empty_request_gets_is_input_priced():
    """stabledomains-like: $1,000 to an empty probe, the listed $4.99 to the seller's own example request."""
    listed = [usdc("4990000")]
    first = judge(listed, seen(usdc("1000000000")))
    assert first["price"] == "above_listed" and wants_example(first)
    again = {"status": 402, "options": [usdc("4990000")], "error": None, "request": SELLER_EXAMPLE}
    v = judge(listed, seen(usdc("1000000000"), again=again))
    assert (v["price"], v["matches_listing"]) == ("input_priced", None)


def test_the_example_must_bring_the_listed_price_for_input_priced():
    listed = [usdc("4990000")]
    again = {"status": 402, "options": [usdc("1000000000")], "error": None, "request": SELLER_EXAMPLE}
    v = judge(listed, seen(usdc("1000000000"), again=again))
    assert (v["price"], v["matches_listing"]) == ("above_listed", False)     # confirmed with the example too
    plain = {"status": 402, "options": [usdc("4990000")], "error": None}
    v = judge(listed, seen(usdc("1000000000"), again=plain))
    assert (v["price"], v["matches_listing"]) == ("varies", None)            # an empty ask again: it varied


def test_a_floating_verdict_that_varies_is_varies():
    listed = [usdc("10000"), xrp("2077")]
    again = {"status": 402, "options": [usdc("10000"), xrp("2077")], "error": None}
    v = judge(listed, seen(usdc("10000"), xrp("2105"), again=again))
    assert (v["price"], v["floating"]) == ("as_listed", "varies")


def test_not_payable_rows_carry_the_same_keys():
    v = judge([usdc("1")], seen(status=404))
    assert v == {"answer": "gone", "price": None, "floating": None, "pay_to": None, "matches_listing": None,
                 "network": None, "asked": None, "differs": []}


def test_sheet_1_rows_judged_again_reproduce_the_audit_split():
    """Each group of the 16 Nov audit, as one row: sheet-2 keeps only the dollar and payee differences."""
    rows = [
        ([usdc("10000"), xrp("2077")], seen(usdc("10000"), xrp("2105"))),     # drift only
        ([usdc("10000"), usdc("9000", asset=EURC)], seen(usdc("10000"), usdc("9100", asset=EURC))),   # euro drift
        ([usdc("10000")], seen(usdc("10010"))),                                # a cent more in USDC
        ([usdc("10000")], seen(usdc("10000", pay_to=B))),                     # another payee
    ]
    before = [rule.judge(listed, s)["matches_listing"] for listed, s in rows]
    after = [judge(listed, s)["matches_listing"] for listed, s in rows]
    assert before == [False, False, False, False]
    assert after == [True, True, False, False]


# --- the seller's own example request -------------------------------------------------------------------------


def offer_with(input_block):
    return {"x402Version": 2, "accepts": [], "extensions": {"bazaar": {"info": {"input": input_block}}}}


def test_the_example_request_is_read_from_the_offer():
    assert example_request(offer_with({"type": "http", "method": "GET", "queryParams": {"domain": "a.com", "n": 2}})) \
        == {"method": "GET", "query": {"domain": "a.com", "n": "2"}}
    assert example_request(offer_with({"type": "http", "method": "POST", "bodyType": "json",
                                       "body": {"q": "x"}})) == {"method": "POST", "json": {"q": "x"}}
    assert example_request(offer_with({"method": "PUT", "body": {"q": "x"}})) is None
    assert example_request(offer_with({"method": "GET", "queryParams": {"q": {"nested": 1}}})) is None
    assert example_request(offer_with({"method": "POST", "bodyType": "form-data", "body": {"q": "x"}})) is None
    assert example_request(offer_with({"method": "POST", "body": {"q": "x" * 20_000}})) is None
    assert example_request({"accepts": []}) is None and example_request(None) is None


def _answer(accepts, info=None):
    required = {"x402Version": 2, "accepts": accepts}
    if info:
        required["extensions"] = {"bazaar": {"info": {"input": info}}}
    header = base64.b64encode(json.dumps(required).encode()).decode()
    return httpx.Response(402, headers={"PAYMENT-REQUIRED": header}, json={})


def test_the_example_rides_along_only_when_asked_and_never_into_the_row():
    from agoranome_inspector.fetch import Fetched

    resp = _answer([{"scheme": "exact", "network": "eip155:8453", "asset": USDC, "amount": "1", "payTo": A}],
                   {"method": "GET", "queryParams": {"domain": "a.com"}})
    fetched = Fetched(url="https://a.example/x", method="GET", status=402,
                      headers={k.lower(): v for k, v in resp.headers.items()}, body=b"{}", truncated=False)
    assert "_example" not in observe(fetched)
    assert observe(fetched, keep_example=True)["_example"] == {"method": "GET", "query": {"domain": "a.com"}}


def test_ask_with_sends_the_example_and_says_so():
    from agoranome_inspector.fetch import SafeFetcher

    sent = []

    def seller(request):
        sent.append((request.method, str(request.url.query, "ascii"), request.content))
        return _answer([{"scheme": "exact", "network": "eip155:8453", "asset": USDC, "amount": "4990000",
                         "payTo": A}])

    fetcher = SafeFetcher(resolver=lambda host, port: ["93.184.216.34"], transport=httpx.MockTransport(seller))
    got = ask_with(fetcher, "https://a.example/price?x=1", {"method": "GET", "query": {"domain": "a.com"}})
    assert got["request"] == SELLER_EXAMPLE and got["options"][0]["amount"] == "4990000"
    assert sent[-1][:2] == ("GET", "x=1&domain=a.com")
    got = ask_with(fetcher, "https://a.example/price", {"method": "POST", "json": {"q": "x"}})
    assert sent[-1][0] == "POST" and json.loads(sent[-1][2]) == {"q": "x"}
