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

from agoranome_inspector import networks
from agoranome_inspector.canonical import sha256_hex
from agoranome_inspector.fetch import FetchError, Fetched, SafeFetcher

MAX_OPTIONS = 16




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


def observe(fetched: Fetched) -> Dict[str, Any]:
    """What the sheet keeps of one answer."""
    offer, where, raw = read_offer(fetched) if fetched.status == 402 else (None, None, None)
    version = (offer or {}).get("x402Version")
    return {
        "method": fetched.method,
        "status": fetched.status,
        "where": where,
        "x402": version if isinstance(version, int) and not isinstance(version, bool) else None,
        "options": options(offer),
        "fair_offer": fair_offer_version(offer),
        "sha256": sha256_hex(raw) if raw is not None else None,
        "error": None,
    }


def ask(fetcher: SafeFetcher, url: str) -> Dict[str, Any]:
    """One unpaid ask: GET, then an empty POST when the GET did not answer 402."""
    try:
        first = fetcher.fetch(url, "GET")
        if first.status == 402:
            return observe(first)
        second = fetcher.fetch(url, "POST", json_body={})
        return observe(second if second.status == 402 else first)
    except FetchError as e:
        return {"method": None, "status": None, "where": None, "x402": None, "options": [], "fair_offer": None,
                "sha256": None, "error": e.kind}


def payable(seen: Dict[str, Any]) -> bool:
    return seen.get("status") == 402 and any(
        o.get("network") and o.get("asset") and o.get("amount") is not None and o.get("pay_to")
        for o in seen.get("options") or [])


def probe(fetcher: SafeFetcher, url: str, *, retry_pause: float = 2.0,
          sleep: Callable[[float], None] = time.sleep, clock: Callable[[], str] = _now) -> Dict[str, Any]:
    """Ask once; a listing that did not give a payable offer is asked a second time before its answer is kept."""
    at = clock()
    seen = ask(fetcher, url)
    attempts = 1
    if not payable(seen) and seen.get("error") != "refused":
        sleep(retry_pause)
        at = clock()
        seen = ask(fetcher, url)
        attempts = 2
    return {"at": at, "attempts": attempts, **seen}
