"""A small fake MPP market: a catalog and endpoints that answer with WWW-Authenticate Payment challenges."""

import base64
import json
from typing import Any, Dict, Optional

import httpx

from agoranome_inspector.mpp import CatalogReader

from fakes import Market

PATH_USD = "0x20C0000000000000000000000000000000000000"
PAY = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"
CATALOG = "https://catalog.example/api/services"


def request_param(amount: str, currency: str = PATH_USD, recipient: str = PAY) -> str:
    body = {"amount": amount, "currency": currency, "recipient": recipient, "methodDetails": {"chainId": 4217}}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def challenge(amount: str, currency: str = PATH_USD, recipient: str = PAY, method: str = "tempo",
              intent: str = "charge", realm: str = "svc.example") -> str:
    return (f'Payment id="c{amount}{method}", realm="{realm}", method="{method}", intent="{intent}", '
            f'request="{request_param(amount, currency, recipient)}", expires="2026-11-16T07:00:00Z"')


def answer(*challenges: str, status: int = 402) -> httpx.Response:
    return httpx.Response(status, headers=[("WWW-Authenticate", c) for c in challenges],
                          json={"type": "https://paymentauth.org/problems/payment-required"})


def payment(amount: Optional[str], method: str = "tempo", currency: str = PATH_USD, intent: str = "charge",
            dynamic: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {"intent": intent, "method": method, "currency": currency, "decimals": 6, "amount": amount}
    if dynamic:
        out.update(dynamic=True, amountHint="5000")
    return out


def service(sid: str, endpoints, category: str = "search") -> Dict[str, Any]:
    return {"id": sid, "name": sid.title(), "url": f"https://{sid}.example", "serviceUrl": f"https://{sid}.example",
            "categories": [category], "status": "active", "realm": f"{sid}.example", "endpoints": endpoints}


def endpoint(method: str, path: str, pay: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {"method": method, "path": path, "description": "x", "payment": pay}


class MppMarket(Market):
    def __init__(self, catalog: Dict[str, Any], sellers):
        super().__init__([], sellers)
        self.catalog = catalog

    def catalog_handler(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=self.catalog)

    def catalog_reader(self) -> CatalogReader:
        return CatalogReader(url=CATALOG, client=httpx.Client(transport=httpx.MockTransport(self.catalog_handler)))


def by_path(routes: Dict[str, Any]):
    """A seller answering by method and path: routes like {"GET /v1/search": response}."""
    def handle(request: httpx.Request) -> httpx.Response:
        found = routes.get(f"{request.method} {request.url.path}")
        if found is None:
            return httpx.Response(405)
        return found() if callable(found) else found
    return handle


def standard_mpp_market() -> MppMarket:
    catalog = {"version": 1, "services": [
        service("fair", [
            endpoint("GET", "/v1/search", payment("10000")),
            endpoint("POST", "/v1/answer", payment("20000")),
            endpoint("GET", "/v1/items/{id}", payment("10000")),
            endpoint("GET", "/health", None),
        ]),
        service("dear", [endpoint("GET", "/v1/data", payment("10000"))]),
        service("dyn", [endpoint("POST", "/v1/llm", payment(None, dynamic=True))], category="ai"),
        service("two", [endpoint("GET", "/v1/q", payment("1", method="stripe", currency="USD"))]),
        service("token", [endpoint("GET", "/v1/x", payment("10000"))]),
        service("put", [endpoint("PUT", "/v1/thing", payment("10000"))]),
    ]}
    both = challenge("10000") + ", " + challenge("1", currency="usd", recipient="acct_1abc", method="stripe")
    sellers = {
        "fair.example": by_path({"GET /v1/search": answer(challenge("10000")),
                                 "POST /v1/answer": answer(challenge("20000"))}),
        "dear.example": by_path({"GET /v1/data": answer(challenge("30000"))}),
        "dyn.example": by_path({"POST /v1/llm": answer(challenge("7000"))}),
        "two.example": by_path({"GET /v1/q": answer(both)}),
        "token.example": by_path({"GET /v1/x": httpx.Response(401, json={"error": "token required"})}),
        "put.example": by_path({}),
    }
    return MppMarket(catalog, sellers)
