"""The unpaid probe, the safe fetcher, the index reader and the run's politeness."""

import base64
import json

import httpx
import pytest

from agoranome_inspector.bazaar import normalize, select
from agoranome_inspector.fetch import FetchError, Fetched, SafeFetcher
from agoranome_inspector.measure import Settings, ask_all
from agoranome_inspector.probe import observe, probe

from fakes import PAY, USDC_BASE, item, option, standard_market


def fetched(status, headers=None, body=b""):
    return Fetched(url="https://s.example/x", method="GET", status=status, headers=headers or {}, body=body)


def test_v2_header_is_read_in_either_base64_alphabet():
    required = {"x402Version": 2, "accepts": [option("5000")], "extensions": {"fair-offer": {"info": {"version": "0.3"}}}}
    raw = json.dumps(required).encode()
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        header = encode(raw).decode().rstrip("=")
        seen = observe(fetched(402, {"payment-required": header}))
        assert seen["where"] == "header" and seen["x402"] == 2 and seen["fair_offer"] == "0.3"
        assert seen["options"] == [{"scheme": "exact", "network": "eip155:8453", "asset": USDC_BASE.lower(),
                                    "amount": "5000", "pay_to": PAY}]


def test_an_unreadable_header_is_kept_as_such():
    seen = observe(fetched(402, {"payment-required": "%%% not base64 %%%"}))
    assert seen["where"] == "header-invalid" and seen["options"] == [] and seen["sha256"]


def test_v1_body_names_the_network_by_its_short_name():
    body = json.dumps({"x402Version": 1, "accepts": [option("1000", v1=True)]}).encode()
    seen = observe(fetched(402, body=body))
    assert seen["where"] == "body" and seen["options"][0]["network"] == "eip155:8453"
    assert seen["options"][0]["amount"] == "1000"


def test_amounts_that_are_not_whole_numbers_are_dropped():
    bad = dict(option("5000"), amount="0.005")
    seen = observe(fetched(402, body=json.dumps({"x402Version": 2, "accepts": [bad]}).encode()))
    assert seen["options"][0]["amount"] is None


def test_a_non_402_keeps_no_offer():
    seen = observe(fetched(200, body=b'{"accepts": [1]}'))
    assert seen["options"] == [] and seen["where"] is None


@pytest.mark.parametrize("url", ["http://s.example/x", "https://127.0.0.1/x", "https://localhost/x",
                                 "https://printer.local/x", "https://user:pw@s.example/x"])
def test_the_fetcher_declines_what_is_not_public_https(url):
    with pytest.raises(FetchError) as e:
        SafeFetcher(resolver=lambda h, p: ["93.184.216.34"]).target(url)
    assert e.value.kind == "refused"


def test_the_fetcher_declines_a_host_that_resolves_inside():
    with pytest.raises(FetchError) as e:
        SafeFetcher(resolver=lambda h, p: ["10.0.0.5"]).target("https://s.example/x")
    assert e.value.kind == "refused"


def test_the_fetcher_pins_the_checked_address_and_keeps_the_host():
    seen = {}

    def handler(request):
        seen["url"], seen["host"] = str(request.url), request.headers["host"]
        return httpx.Response(402, json={"accepts": [option("5000")]})

    fetcher = SafeFetcher(resolver=lambda h, p: ["93.184.216.34"], transport=httpx.MockTransport(handler))
    assert fetcher.fetch("https://s.example/x?q=1").status == 402
    assert seen == {"url": "https://93.184.216.34/x?q=1", "host": "s.example"}


def test_a_refused_url_is_not_asked_twice():
    calls = []
    found = probe(SafeFetcher(resolver=lambda h, p: ["93.184.216.34"]), "http://s.example/x",
                  sleep=lambda s: calls.append(s))
    assert found["error"] == "refused" and found["attempts"] == 1 and not calls


def test_the_index_is_read_page_by_page():
    market = standard_market()
    found = market.reader().read()
    assert len(found["listings"]) == 9 and found["complete"] and found["total_reported"] == 9
    assert found["digest"].startswith("0x")


def test_select_keeps_real_demand_once_per_resource():
    a = normalize(item("https://a.example/x", payers=3, calls=3))
    b = normalize(item("https://a.example/x", payers=9, calls=40))
    c = normalize(item("https://c.example/x", payers=2))
    chosen = select([a, b, c])
    assert [x["resource"] for x in chosen] == ["https://a.example/x"] and chosen[0]["payers_30d"] == 9


def test_a_run_keeps_to_its_per_host_cap_and_its_budget():
    market = standard_market()
    listings = [normalize(item(f"https://honest.example/{i}", payers=10 - i)) for i in range(5)]
    seen = ask_all(listings, market.fetcher(), Settings(per_host=2, host_pause=0, retry_pause=0))
    assert sorted(seen) == ["https://honest.example/0", "https://honest.example/1"]
    ticks = iter([0, 0, 10, 10, 10, 10])
    seen = ask_all(listings, market.fetcher(), Settings(budget_seconds=5, host_pause=0, retry_pause=0),
                   monotonic=lambda: next(ticks))
    assert sorted(seen) == ["https://honest.example/0"]


@pytest.mark.parametrize("value,expected", [("5000", "5000"), (5000, "5000"), ("007", "7"), ("²", None),
                                            ("١٢", None), ("-1", None), ("1e3", None), (True, None), ("9" * 79, None)])
def test_amounts_are_plain_whole_numbers(value, expected):
    from agoranome_inspector.networks import amount

    assert amount(value) == expected


def test_a_seller_cannot_bloat_a_row():
    huge = dict(option("5000"), payTo="0x" + "a" * 5000, scheme="x" * 5000)
    seen = observe(fetched(402, body=json.dumps({"x402Version": 2, "accepts": [huge] * 40}).encode()))
    assert len(seen["options"]) == 16
    assert all(len(o["pay_to"]) == 200 and len(o["scheme"]) == 200 for o in seen["options"])


def test_one_network_written_two_ways_is_one_network():
    from agoranome_inspector.networks import network

    assert network("algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8=") == "algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k"
    assert network("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d") == "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
    assert network("Base") == "eip155:8453" and network("eip155:8453") == "eip155:8453"
