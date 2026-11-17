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

"""The unpaid probe: ask a listing for its offer, the way any buyer agent's first call does, and keep what came back.

A GET first, then an empty JSON POST if the GET did not answer 402 (lifted from the lab's lint.probe). x402 v2
puts the offer in the PAYMENT-REQUIRED header (base64 JSON), v1 in the body. What is kept is only what the
sheet's rule reads: the status, where the offer was, each payment option's scheme, network, asset, amount and
pay-to, the Fair Offer block's version, and a SHA-256 of the offer as received so a seller can dispute a row
against its own logs. Nothing is paid and nothing else of the answer is kept.
"""

import base64
import binascii
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from agoranome_inspector import networks
from agoranome_inspector.canonical import sha256_hex
from agoranome_inspector.fetch import FetchError, Fetched, SafeFetcher

MAX_OPTIONS = 16
MAX_EXAMPLE = 16_384       # bytes of an example input the inspector will send (as mpp.MAX_EXAMPLE)
SELLER_EXAMPLE = "seller_example"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _b64_json(text: str) -> Any:
    raw = text.strip()
    padded = raw + "=" * (-len(raw) % 4)
    for decode in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return json.loads(decode(padded.encode("ascii")))
        except (binascii.Error, ValueError, UnicodeDecodeError, RecursionError):
            continue
    raise ValueError("not base64 JSON")


def read_offer(fetched: Fetched) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[bytes]]:
    """The payment requirements in an answer, where they were (header, body or header-invalid), and their raw
    bytes as received (for the hash)."""
    header = fetched.headers.get("payment-required")
    if header:
        try:
            offer = _b64_json(header)
        except ValueError:
            return None, "header-invalid", header.encode("utf-8", "replace")
        return (offer if isinstance(offer, dict) else None), "header", header.encode("utf-8", "replace")
    try:
        body = json.loads(fetched.body or b"{}")
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None, None, None
    if isinstance(body, dict) and body.get("accepts"):
        return body, "body", fetched.body
    return None, None, None


def options(offer: Optional[Dict[str, Any]]) -> List[Dict[str, Optional[str]]]:
    """Each payment option, normalized and sorted so the same offer always gives the same list."""
    found = []
    for option in (offer or {}).get("accepts") or []:
        if not isinstance(option, dict):
            continue
        net = networks.strict_network(option.get("network"))
        found.append({
            "scheme": networks.strict_scheme(option.get("scheme")),
            "network": net,
            "asset": networks.identifier(option.get("asset")),
            "amount": networks.amount(option.get("amount", option.get("maxAmountRequired"))),
            "pay_to": networks.pay_to(option.get("payTo"), net),
        })
    found.sort(key=lambda o: tuple(o[k] or "" for k in ("network", "asset", "amount", "pay_to", "scheme")))
    return found[:MAX_OPTIONS]


def fair_offer_version(offer: Optional[Dict[str, Any]]) -> Optional[str]:
    block = ((offer or {}).get("extensions") or {}).get("fair-offer")
    info = block.get("info") if isinstance(block, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    return networks.version(version) if version else None


def _scalar(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def example_request(offer: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The request the offer's own discovery block (x402 v2 extensions.bazaar.info.input) gives as its example:
    {"method": "GET", "query": {...}} or {"method": "POST", "json": ...}, or None when it gives none the inspector
    will send (another method, a non-JSON body, a value that is not plain, or more than MAX_EXAMPLE bytes). An
    endpoint priced by its input quotes its ceiling to an empty request; this is the request a buyer agent sends.
    The example is sent, never published."""
    extensions = (offer or {}).get("extensions") if isinstance(offer, dict) else None
    bazaar = extensions.get("bazaar") if isinstance(extensions, dict) else None
    info = bazaar.get("info") if isinstance(bazaar, dict) else None
    given = info.get("input") if isinstance(info, dict) else None
    if not isinstance(given, dict):
        return None
    method = str(given.get("method") or "").upper() or None
    query, body = given.get("queryParams"), given.get("body")
    try:
        if isinstance(body, (dict, list)) and body and method in (None, "POST") \
                and str(given.get("bodyType") or "json").lower() == "json":
            if len(json.dumps(body)) <= MAX_EXAMPLE:
                return {"method": "POST", "json": body}
            return None
        if isinstance(query, dict) and query and method in (None, "GET"):
            plain = {str(k): _scalar(v) for k, v in query.items()}
            if all(v is not None for v in plain.values()) and len(urlencode(plain)) <= MAX_EXAMPLE:
                return {"method": "GET", "query": plain}
    except (TypeError, ValueError, RecursionError):
        return None
    return None


def observe(fetched: Fetched, keep_example: bool = False) -> Dict[str, Any]:
    """What the sheet keeps of one answer. With keep_example, the offer's example request rides along under
    "_example" for the run to use; the run takes it out before anything is kept."""
    offer, where, raw = read_offer(fetched) if fetched.status == 402 else (None, None, None)
    version = (offer or {}).get("x402Version")
    found = {
        "method": fetched.method,
        "status": fetched.status,
        "where": where,
        "x402": version if isinstance(version, int) and not isinstance(version, bool) else None,
        "options": options(offer),
        "fair_offer": fair_offer_version(offer),
        "sha256": sha256_hex(raw) if raw is not None else None,
        "error": None,
    }
    if keep_example:
        found["_example"] = example_request(offer)
    return found


def _nothing(kind: str) -> Dict[str, Any]:
    return {"method": None, "status": None, "where": None, "x402": None, "options": [], "fair_offer": None,
            "sha256": None, "error": kind}


def ask(fetcher: SafeFetcher, url: str, *, keep_example: bool = False) -> Dict[str, Any]:
    """One unpaid ask: GET, then an empty POST when the GET did not answer 402."""
    try:
        first = fetcher.fetch(url, "GET")
        if first.status == 402:
            return observe(first, keep_example)
        second = fetcher.fetch(url, "POST", json_body={})
        return observe(second if second.status == 402 else first, keep_example)
    except FetchError as e:
        return _nothing(e.kind)


def ask_with(fetcher: SafeFetcher, url: str, example: Dict[str, Any]) -> Dict[str, Any]:
    """One unpaid ask with the offer's own example request (example_request); the answer says so."""
    try:
        if example.get("method") == "POST":
            fetched = fetcher.fetch(url, "POST", json_body=example.get("json"))
        else:
            target = url + ("&" if "?" in url else "?") + urlencode(example.get("query") or {})
            fetched = fetcher.fetch(target, "GET")
        found = observe(fetched)
    except FetchError as e:
        found = _nothing(e.kind)
    return {**found, "request": SELLER_EXAMPLE}


def payable(seen: Dict[str, Any]) -> bool:
    return seen.get("status") == 402 and any(
        o.get("network") and o.get("asset") and o.get("amount") is not None and o.get("pay_to")
        for o in seen.get("options") or [])


def probe(fetcher: SafeFetcher, url: str, *, retry_pause: float = 2.0,
          sleep: Callable[[float], None] = time.sleep, clock: Callable[[], str] = _now,
          keep_example: bool = False) -> Dict[str, Any]:
    """Ask once; a listing that did not give a payable offer is asked a second time before its answer is kept."""
    at = clock()
    seen = ask(fetcher, url, keep_example=keep_example)
    attempts = 1
    if not payable(seen) and seen.get("error") != "refused":
        sleep(retry_pause)
        at = clock()
        seen = ask(fetcher, url, keep_example=keep_example)
        attempts = 2
    return {"at": at, "attempts": attempts, **seen}
