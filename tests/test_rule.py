"""The sheet's rule, case by case."""

import pytest

from agoranome_inspector.rule import answer, judge

USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
SEPOLIA_USDC = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
A = "0x1111111111111111111111111111111111111111"
B = "0x2222222222222222222222222222222222222222"


def o(amount, pay_to=A, network="eip155:8453", asset=USDC):
    return {"scheme": "exact", "network": network, "asset": asset, "amount": amount, "pay_to": pay_to}


def seen(*options, status=402, error=None):
    return {"status": status, "options": list(options), "error": error}


@pytest.mark.parametrize("observed,expected", [
    (None, "not_asked"),
    ({"error": "refused", "options": []}, "declined"),
    ({"error": "unreachable", "options": []}, "unreachable"),
    (seen(o("5000")), "payable"),
    (seen(o("5000", pay_to=None)), "unreadable_offer"),
    (seen(), "unreadable_offer"),
    (seen(status=200), "no_payment_asked"),
    (seen(status=404), "gone"),
    (seen(status=410), "gone"),
    (seen(status=401), "http_4xx"),
    (seen(status=503), "http_5xx"),
    (seen(status=302), "other"),
])
def test_answer(observed, expected):
    assert answer(observed) == expected


def test_as_listed_is_kept():
    v = judge([o("5000")], seen(o("5000")))
    assert (v["price"], v["pay_to"], v["kept"], v["network"]) == ("as_listed", "as_listed", True, "mainnet")
    assert v["asked"] == {"network": "eip155:8453", "asset": USDC, "amount": "5000", "pay_to": A}


def test_below_listed_is_kept():
    v = judge([o("5000")], seen(o("4000")))
    assert (v["price"], v["kept"]) == ("below_listed", True)


def test_above_listed_is_not_kept():
    v = judge([o("5000")], seen(o("10000")))
    assert (v["price"], v["kept"]) == ("above_listed", False)


def test_cheapest_live_option_is_compared():
    v = judge([o("5000")], seen(o("9000"), o("5000")))
    assert v["price"] == "as_listed"


def test_different_pay_to_is_not_kept():
    v = judge([o("5000")], seen(o("5000", pay_to=B)))
    assert (v["price"], v["pay_to"], v["kept"]) == ("as_listed", "different", False)


def test_listed_option_missing_live():
    v = judge([o("5000")], seen(o("5000", network="eip155:84532", asset=SEPOLIA_USDC)))
    assert (v["price"], v["pay_to"], v["kept"], v["network"]) == (
        "listed_option_missing", "listed_option_missing", False, "testnet_only")


def test_listing_without_price_is_not_judged_on_price():
    v = judge([], seen(o("5000")))
    assert (v["price"], v["pay_to"], v["kept"]) == ("not_listed", "not_listed", None)


def test_listing_without_pay_to_keeps_kept_open():
    v = judge([o("5000", pay_to=None)], seen(o("5000")))
    assert (v["price"], v["pay_to"], v["kept"]) == ("as_listed", "not_listed", None)


def test_one_of_two_listed_options_above_is_above():
    listed = [o("5000"), o("5000", network="eip155:137", asset="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359")]
    live = seen(o("5000"), o("7000", network="eip155:137", asset="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"))
    assert judge(listed, live)["price"] == "above_listed"


def test_not_payable_has_no_price_verdict():
    v = judge([o("5000")], seen(status=404))
    assert v == {"answer": "gone", "price": None, "pay_to": None, "network": None, "kept": None, "asked": None}
