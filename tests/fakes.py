"""A small fake x402 market for offline tests: an index that pages, and sellers that behave well or badly."""

import base64
import json
from typing import Any, Callable, Dict, List, Optional

import httpx

from agoranome_inspector.bazaar import IndexReader
from agoranome_inspector.fetch import SafeFetcher

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_BASE_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
PAY = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"
INDEX = "https://index.example/discovery/resources"


def option(amount: str, pay_to: str = PAY, network: str = "eip155:8453", asset: str = USDC_BASE,
           v1: bool = False) -> Dict[str, Any]:
    if v1:
        return {"scheme": "exact", "network": {"eip155:8453": "base", "eip155:84532": "base-sepolia"}[network],
                "maxAmountRequired": amount, "asset": asset, "payTo": pay_to, "resource": "x", "maxTimeoutSeconds": 60}
    return {"scheme": "exact", "network": network, "amount": amount, "asset": asset, "payTo": pay_to,
            "maxTimeoutSeconds": 60}


def item(resource: str, amount: str = "5000", payers: int = 5, calls: int = 20, pay_to: str = PAY,
         description: str = "Web search for agents") -> Dict[str, Any]:
    return {"resource": resource, "type": "http", "x402Version": 2, "accepts": [option(amount, pay_to)],
            "description": description, "serviceName": resource.split("/")[2],
            "quality": {"l30DaysUniquePayers": payers, "l30DaysTotalCalls": calls, "score": 0.5},
            "lastUpdated": "2026-11-10T00:00:00Z"}


def v2_answer(accepts: List[Dict[str, Any]], fair_offer: Optional[str] = None) -> httpx.Response:
    required = {"x402Version": 2, "error": "Payment required", "resource": {"url": "x"}, "accepts": accepts}
    if fair_offer:
        required["extensions"] = {"fair-offer": {"info": {"version": fair_offer}}}
    header = base64.b64encode(json.dumps(required).encode()).decode()
    return httpx.Response(402, headers={"PAYMENT-REQUIRED": header}, json={})


def v1_answer(accepts: List[Dict[str, Any]]) -> httpx.Response:
    return httpx.Response(402, json={"x402Version": 1, "error": "X-PAYMENT header is required", "accepts": accepts})


Seller = Callable[[httpx.Request], httpx.Response]


class Market:
    """Index items and, for each host, how it answers."""

    def __init__(self, items: List[Dict[str, Any]], sellers: Dict[str, Seller], page_size: int = 2):
        self.items = items
        self.sellers = sellers
        self.page_size = page_size
        self.asked: List[str] = []

    def index_handler(self, request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", 0))
        limit = int(request.url.params.get("limit", self.page_size))
        limit = min(limit, self.page_size)
        page = self.items[offset: offset + limit]
        return httpx.Response(200, json={"items": page, "pagination": {"limit": limit, "offset": offset,
                                                                        "total": len(self.items)}})

    def seller_handler(self, request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        self.asked.append(f"{request.method} {host}{request.url.path}")
        seller = self.sellers.get(host)
        if seller is None:
            raise httpx.ConnectError("no such host", request=request)
        return seller(request)

    def reader(self) -> IndexReader:
        client = httpx.Client(transport=httpx.MockTransport(self.index_handler))
        return IndexReader(url=INDEX, client=client, page_size=self.page_size, sleep=lambda s: None)

    def fetcher(self) -> SafeFetcher:
        return SafeFetcher(resolver=lambda host, port: ["93.184.216.34"],
                           transport=httpx.MockTransport(self.seller_handler))


def honest(amount: str = "5000", pay_to: str = PAY, fair_offer: Optional[str] = None) -> Seller:
    return lambda request: v2_answer([option(amount, pay_to)], fair_offer)


def post_only(amount: str = "5000") -> Seller:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(405)
        return v1_answer([option(amount, v1=True)])
    return answer


def status(code: int) -> Seller:
    return lambda request: httpx.Response(code, json={"ok": code < 400})


def down() -> Seller:
    def answer(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)
    return answer


def standard_market() -> Market:
    """Nine listings, eight with real demand, each seller behaving one way."""
    items = [
        item("https://honest.example/search", "5000"),
        item("https://pricey.example/search", "5000"),
        item("https://swap.example/search", "5000"),
        item("https://legacy.example/search", "1000"),
        item("https://free.example/search", "1000"),
        item("https://gone.example/search", "1000"),
        item("https://down.example/search", "1000"),
        item("http://plain.example/search", "1000"),
        item("https://quiet.example/search", "1000", payers=2),
    ]
    sellers = {
        "honest.example": honest("5000", fair_offer="0.3"),
        "pricey.example": honest("10000"),
        "swap.example": honest("5000", OTHER),
        "legacy.example": post_only("1000"),
        "free.example": status(200),
        "gone.example": status(404),
        "down.example": down(),
        "quiet.example": honest("1000"),
    }
    return Market(items, sellers)
