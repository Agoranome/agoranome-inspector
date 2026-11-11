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

"""MPP, the Machine Payments Protocol (the IETF draft draft-ryan-httpauth-payment): its public catalog, its unpaid
402 challenges, and one run of the measurer over it, judged into a sheet under the rule `mpp-1`.

What the catalog lists (https://mpp.dev/api/services): services, each with a `serviceUrl` and `endpoints`, each
endpoint with an HTTP `method`, a `path` and a `payment` (`method`, `intent`, `currency`, `amount` in base units,
`decimals`, and `dynamic` when the price depends on the request).

What an endpoint answers unpaid: HTTP 402 with one `WWW-Authenticate: Payment ...` header for each way it can be
paid. Its `request` parameter is base64url of JSON naming at least `amount`, `currency` and `recipient`.
"""

import base64
import binascii
import csv
import io
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

import httpx

from agoranome_inspector import networks
from agoranome_inspector.canonical import digest, sha256_hex
from agoranome_inspector.fetch import FetchError, SafeFetcher
from agoranome_inspector.merkle import leaf_hash
from agoranome_inspector.rule_mpp import METHOD, RULE, answer, judge

CATALOG_URL = "https://mpp.dev/api/services"
MARKET = "mpp"
KIND = "agoranome.mpp-sheet"
RUN_KIND = "agoranome.mpp-run"
FORMAT = 1
ASKED_METHODS = ("GET", "POST")
MAX_CHALLENGES = 16
CAP = 200
TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
ISO_CODE = re.compile(r"^[A-Za-z]{3,5}$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any, lower: bool = False) -> Optional[str]:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()[:CAP]
    if not text:
        return None
    return text.lower() if lower else text


def currency(value: Any) -> Optional[str]:
    """A currency as compared: an ISO code in lower case, else an address or asset id (strict, see networks)."""
    text = _text(value)
    if text is None:
        return None
    return text.lower() if ISO_CODE.match(text) else networks.identifier(text)


def token(value: Any) -> Optional[str]:
    """A method, intent or service id: a short word, in lower case; None for anything else."""
    text = networks.strict_scheme(value)
    return text.lower() if text else None


def category(value: Any) -> str:
    text = (_text(value, lower=True) or "").replace(" ", "-")
    return text if re.match(r"^[a-z0-9][a-z0-9_-]{0,39}$", text) else "other"


# --- The 402 challenge -------------------------------------------------------------------------------------------

def parse_challenges(values: Iterable[str]) -> List[Dict[str, Any]]:
    """Every challenge in a list of WWW-Authenticate header values (RFC 9110, section 11.6.1): each value may hold
    several challenges separated by commas, each a scheme and its `name=value` parameters, a value being a token
    or a quoted string."""
    found: List[Dict[str, Any]] = []
    for value in values:
        text = str(value)
        i, n = 0, len(text)
        current: Optional[Dict[str, Any]] = None
        while i < n:
            while i < n and text[i] in " \t,":
                i += 1
            m = TOKEN.match(text, i)
            if not m:
                i += 1          # a character no rule allows here: skip it and look for the next token
                continue
            word, i = m.group(0), m.end()
            j = i
            while j < n and text[j] in " \t":
                j += 1
            if j < n and text[j] == "=" and not (j + 1 < n and text[j + 1] == "=" and current is None):
                i = j + 1
                while i < n and text[i] in " \t":
                    i += 1
                if i < n and text[i] == '"':
                    i += 1
                    out = []
                    while i < n and text[i] != '"':
                        if text[i] == "\\" and i + 1 < n:
                            i += 1
                        out.append(text[i])
                        i += 1
                    i += 1
                    param = "".join(out)
                else:
                    start = i
                    while i < n and text[i] not in ", \t":
                        i += 1
                    param = text[start:i]
                if current is not None and len(current["params"]) < 32:
                    current["params"].setdefault(word.lower(), param[:8192])
            else:
                current = {"scheme": word, "params": {}}
                found.append(current)
                i = j
    return found


def _b64url_json(text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text or len(text) > 8192:
        return None
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        data = json.loads(raw, parse_float=str)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def offers(values: Iterable[str]) -> List[Dict[str, Optional[str]]]:
    """The Payment challenges as compared: method, intent, currency, amount and recipient. Nothing else the seller
    wrote is kept (the realm and description are free text)."""
    out = []
    for challenge in parse_challenges(values):
        if challenge["scheme"].lower() != "payment":
            continue
        params = challenge["params"]
        request = _b64url_json(params.get("request")) or {}
        out.append({
            "method": token(params.get("method")),
            "intent": token(params.get("intent")),
            "currency": currency(request.get("currency")),
            "amount": networks.amount(request.get("amount")),
            "recipient": networks.identifier(_text(request.get("recipient"))),
        })
    unique = {json.dumps(o, sort_keys=True): o for o in out}
    return [unique[k] for k in sorted(unique)][:MAX_CHALLENGES]


def observe(fetched) -> Dict[str, Any]:
    values = list(fetched.www_authenticate or [])
    raw = "\n".join(values).encode("utf-8", "replace")
    return {"method": fetched.method, "status": fetched.status, "where": "www-authenticate" if values else None,
            "options": offers(values), "also_x402": "payment-required" in fetched.headers,
            "sha256": sha256_hex(raw) if values else None}


def ask(fetcher: SafeFetcher, listing: Dict[str, Any]) -> Dict[str, Any]:
    """One unpaid request with the listed HTTP method (an empty JSON body for POST)."""
    method = listing["http_method"]
    nothing = {"method": method, "status": None, "where": None, "options": [], "also_x402": False, "sha256": None}
    if method not in ASKED_METHODS:
        return {**nothing, "error": "refused"}
    try:
        fetched = fetcher.fetch(listing["url"], method, {} if method == "POST" else None)
    except FetchError as e:
        return {**nothing, "error": e.kind}
    return {**observe(fetched), "error": None}


def probe(fetcher: SafeFetcher, listing: Dict[str, Any], *, retry_pause: float = 2.0,
          sleep: Callable[[float], None] = time.sleep, clock: Callable[[], str] = _now) -> Dict[str, Any]:
    """Ask, and ask once more a little later when the first answer gives no payable challenge."""
    found = {"at": clock(), "attempts": 1, **ask(fetcher, listing)}
    if answer(found) != "payable" and found.get("error") != "refused":
        sleep(retry_pause)
        found = {"at": clock(), "attempts": 2, **ask(fetcher, listing)}
    return found


# --- The catalog -------------------------------------------------------------------------------------------------

def listings(catalog: Dict[str, Any]) -> Dict[str, Any]:
    """Every paid endpoint in the catalog as a listing, and how many endpoints were left out and why."""
    out: Dict[str, Dict[str, Any]] = {}
    skipped = {"free": 0, "path_needs_parameters": 0, "not_https": 0, "bad_method": 0}
    services = [s for s in catalog.get("services") or [] if isinstance(s, dict)]
    for service in services:
        base = str(service.get("serviceUrl") or service.get("url") or "").strip().rstrip("/")
        categories = service.get("categories") or []
        kind = category(categories[0] if isinstance(categories, list) and categories else None)
        for endpoint in service.get("endpoints") or []:
            if not isinstance(endpoint, dict):
                continue
            pay = endpoint.get("payment")
            if not isinstance(pay, dict):
                skipped["free"] += 1
                continue
            path = str(endpoint.get("path") or "/").strip()
            if "{" in path or "}" in path:
                skipped["path_needs_parameters"] += 1
                continue
            url = base + (path if path.startswith("/") else "/" + path)
            if not url.startswith("https://"):
                skipped["not_https"] += 1
                continue
            method = (_text(endpoint.get("method")) or "GET").upper()
            if not re.match(r"^[A-Z]{3,7}$", method):
                skipped["bad_method"] += 1
                continue
            dynamic = bool(pay.get("dynamic"))
            decimals = pay.get("decimals")
            listed = {
                "method": token(pay.get("method")),
                "intent": token(pay.get("intent")),
                "currency": currency(pay.get("currency")),
                "amount": None if dynamic else networks.amount(pay.get("amount")),
                "decimals": decimals if isinstance(decimals, int) and not isinstance(decimals, bool) else None,
                "dynamic": dynamic,
                "recipient": None,
            }
            resource = f"{method} {url}"
            out.setdefault(resource, {
                "resource": resource, "url": url, "http_method": method,
                "host": (urlsplit(url).hostname or "").lower(),
                "service": token(service.get("id")), "category": kind,
                "listed": [listed], "payers_30d": 0, "calls_30d": 0,
            })
    return {"services": len(services), "listings": [out[k] for k in sorted(out)], "skipped": skipped}


class CatalogReader:
    def __init__(self, url: str = CATALOG_URL, client: Optional[httpx.Client] = None,
                 max_bytes: int = 20_000_000):
        self.url = url
        self.client = client or httpx.Client(timeout=30.0, follow_redirects=True, headers={
            "Accept": "application/json", "User-Agent": "Agoranome-inspector/0.1 (catalog read)"})
        self.max_bytes = max_bytes

    def read(self) -> Dict[str, Any]:
        resp = self.client.get(self.url)
        resp.raise_for_status()
        if len(resp.content) > self.max_bytes:
            raise RuntimeError(f"the catalog is larger than {self.max_bytes} bytes")
        catalog = json.loads(resp.content, parse_float=str)
        found = listings(catalog)
        return {"url": self.url, "version": catalog.get("version"), "digest": digest(catalog), **found}


# --- One run and its sheet ---------------------------------------------------------------------------------------

def run(run_id: Optional[str] = None, *, reader: Optional[CatalogReader] = None,
        fetcher: Optional[SafeFetcher] = None, settings=None, clock: Callable[[], str] = _now) -> Dict[str, Any]:
    """Read the catalog and ask every paid endpoint. The result is the run file."""
    from agoranome_inspector.measure import Settings, ask_all

    settings = settings or Settings()
    reader = reader or CatalogReader()
    fetcher = fetcher or SafeFetcher()
    read_at = clock()
    catalog = reader.read()
    started = clock()
    seen = ask_all(catalog["listings"], fetcher, settings, clock=clock,
                   asker=lambda x: probe(fetcher, x, retry_pause=settings.retry_pause, clock=clock),
                   again=lambda x: ask(fetcher, x), judge_fn=judge)
    ended = clock()
    return {
        "kind": RUN_KIND,
        "id": run_id or f"mpp-{started[:10]}",
        "catalog": {"url": catalog["url"], "read_at": read_at, "version": catalog["version"],
                    "digest": catalog["digest"], "services": catalog["services"],
                    "endpoints": len(catalog["listings"]), "skipped": catalog["skipped"]},
        "probe": {"started": started, "ended": ended, "user_agent": fetcher.user_agent,
                  "per_host": settings.per_host, "budget_seconds": int(settings.budget_seconds),
                  "asked": len(seen), "chosen": len(catalog["listings"])},
        "listings": catalog["listings"],
        "seen": seen,
    }


def build(found: Dict[str, Any]) -> Dict[str, Any]:
    """The MPP sheet from a run file."""
    from agoranome_inspector import sheet as sheet_lib

    rows = sorted((sheet_lib.row(x, found["seen"].get(x["resource"]), rule=RULE) for x in found["listings"]),
                  key=lambda r: r["resource"])
    return {
        "kind": KIND,
        "format": FORMAT,
        "market": MARKET,
        "id": found["id"],
        "rule": RULE,
        "method": METHOD,
        "licence": sheet_lib.LICENCE,
        "selection": {**found["catalog"], "demand": "not stated by the catalog; every paid endpoint is asked"},
        "probe": found["probe"],
        "rows": rows,
        "summary": sheet_lib.summarize(rows),
    }


CSV_COLUMNS = ["resource", "http_method", "url", "host", "service", "category", "answer", "price", "pay_to",
               "matches_listing", "listed_method", "listed_intent", "listed_currency", "listed_amount",
               "listed_dynamic", "asked_method", "asked_currency", "asked_amount", "asked_recipient", "also_x402",
               "status", "seen_at", "leaf"]


def to_csv(sheet: Dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for r in sheet["rows"]:
        verdict, seen = r["verdict"], r.get("seen") or {}
        listed = (r.get("listed") or [None])[0] or {}
        asked = verdict.get("asked") or {}
        matches = verdict.get("matches_listing")
        writer.writerow([
            r["resource"], r.get("http_method") or "", r.get("url") or "", r["host"], r.get("service") or "",
            r["category"], verdict["answer"], verdict.get("price") or "", verdict.get("pay_to") or "",
            "" if matches is None else str(matches).lower(),
            listed.get("method") or "", listed.get("intent") or "", listed.get("currency") or "",
            listed.get("amount") or "", str(bool(listed.get("dynamic"))).lower(),
            asked.get("method") or "", asked.get("currency") or "", asked.get("amount") or "",
            asked.get("recipient") or "", str(bool(seen.get("also_x402"))).lower(), seen.get("status") or "",
            seen.get("at") or "", leaf_hash(r),
        ])
    return out.getvalue()
