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


def test_as_listed_matches():
    v = judge([o("5000")], seen(o("5000")))
    assert (v["price"], v["pay_to"], v["matches_listing"], v["network"]) == ("as_listed", "as_listed", True, "mainnet")
    assert v["asked"] == {"network": "eip155:8453", "asset": USDC, "amount": "5000", "pay_to": A}


def test_below_listed_matches():
    v = judge([o("5000")], seen(o("4000")))
    assert (v["price"], v["matches_listing"]) == ("below_listed", True)


def test_above_listed_does_not_match():
    v = judge([o("5000")], seen(o("10000")))
    assert (v["price"], v["matches_listing"]) == ("above_listed", False)


def test_a_higher_price_beside_the_listed_one_counts():
    # The listed price is offered, but so is a higher one the listing never states: an agent may be asked for it.
    v = judge([o("5000")], seen(o("9000"), o("5000")))
    assert (v["price"], v["matches_listing"], v["asked"]["amount"]) == ("above_listed", False, "9000")


def test_tiers_the_listing_states_are_as_listed():
    v = judge([o("1000"), o("2000")], seen(o("1000"), o("2000")))
    assert (v["price"], v["matches_listing"]) == ("as_listed", True)


def test_different_pay_to_does_not_match():
    v = judge([o("5000")], seen(o("5000", pay_to=B)))
    assert (v["price"], v["pay_to"], v["matches_listing"]) == ("as_listed", "different", False)


def test_listed_option_missing_live():
    v = judge([o("5000")], seen(o("5000", network="eip155:84532", asset=SEPOLIA_USDC)))
    assert (v["price"], v["pay_to"], v["matches_listing"], v["network"]) == (
        "listed_option_missing", "listed_option_missing", False, "testnet_only")


def test_listing_without_price_is_not_judged_on_price():
    v = judge([], seen(o("5000")))
    assert (v["price"], v["pay_to"], v["matches_listing"]) == ("not_listed", "not_listed", None)


def test_listing_without_pay_to_leaves_the_match_open():
    v = judge([o("5000", pay_to=None)], seen(o("5000")))
    assert (v["price"], v["pay_to"], v["matches_listing"]) == ("as_listed", "not_listed", None)


def test_one_of_two_listed_options_above_is_above():
    listed = [o("5000"), o("5000", network="eip155:137", asset="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359")]
    live = seen(o("5000"), o("7000", network="eip155:137", asset="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"))
    assert judge(listed, live)["price"] == "above_listed"


def test_not_payable_has_no_price_verdict():
    v = judge([o("5000")], seen(status=404))
    assert v == {"answer": "gone", "price": None, "pay_to": None, "matches_listing": None, "network": None,
                 "asked": None, "differs": []}


def test_two_listed_tiers_on_one_network_compare_like_with_like():
    listed = [o("10000"), dict(o("50000"), scheme="upto")]
    live = seen(o("10000"), dict(o("50000"), scheme="upto"))
    v = judge(listed, live)
    assert (v["price"], v["pay_to"], v["matches_listing"], v["differs"]) == ("as_listed", "as_listed", True, [])


def test_an_exact_match_wins_over_a_cheaper_option():
    v = judge([o("1000")], seen(o("900"), o("1000")))
    assert v["price"] == "as_listed" and v["asked"]["amount"] == "1000"


def test_a_scheme_missing_live_falls_back_to_the_network_and_asset():
    v = judge([dict(o("1000"), scheme="upto")], seen(o("1000")))
    assert v["price"] == "as_listed"


def test_an_unlisted_address_beside_the_listed_one_counts():
    v = judge([o("1000")], seen(o("1000", pay_to=B), o("1000", pay_to=A)))
    assert (v["pay_to"], v["asked"]["pay_to"], v["matches_listing"]) == ("different", B, False)


def test_addresses_the_listing_states_are_as_listed():
    v = judge([o("1000"), o("1000", pay_to=B)], seen(o("1000", pay_to=B), o("1000", pay_to=A)))
    assert v["pay_to"] == "as_listed"


def test_differs_names_each_option_that_differs():
    listed = [o("5000"), o("5000", network="eip155:137", asset="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359")]
    live = seen(o("5000"), o("7000", pay_to=B, network="eip155:137", asset="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"))
    v = judge(listed, live)
    assert v["differs"] == [{"network": "eip155:137", "asset": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
                             "scheme": "exact", "listed_amount": "5000", "listed_pay_to": A, "asked_amount": "7000",
                             "asked_pay_to": B, "price": "above_listed", "pay_to": "different"}]
    assert v["asked"]["amount"] == "7000"     # the first listed option in sorted order: "eip155:137" < "eip155:8453"
    assert v["matches_listing"] is False


def test_a_difference_both_asks_give_is_confirmed():
    first = seen(o("10000"))
    first["again"] = seen(o("10000"))
    v = judge([o("5000")], first)
    assert (v["price"], v["matches_listing"]) == ("above_listed", False)


def test_a_difference_the_second_ask_does_not_give_varies():
    first = seen(o("5000", pay_to=B))
    first["again"] = seen(o("5000"))
    v = judge([o("5000")], first)
    assert (v["price"], v["pay_to"], v["matches_listing"]) == ("as_listed", "varies", None)
    first["again"] = seen(status=429)
    v = judge([o("5000")], first)
    assert (v["price"], v["pay_to"], v["matches_listing"]) == ("varies", "varies", None)


def test_which_first_answers_are_asked_again():
    from agoranome_inspector.rule import needs_confirmation

    assert needs_confirmation(judge([o("5000")], seen(o("9000"))))
    assert needs_confirmation(judge([o("5000")], seen(o("5000", pay_to=B))))
    assert not needs_confirmation(judge([o("5000")], seen(o("4000"))))
    assert not needs_confirmation(judge([o("5000")], seen(status=404)))
