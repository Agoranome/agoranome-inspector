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

"""The list of where to look: Coinbase's x402 Bazaar index, read page by page.

Lifted from the lab's measurer (AEAx src/revenue/insights/sources.py and analysis.py). The index lists every
paid endpoint whose payment settled through Coinbase's facilitator, with 30-day calls and unique payers. The
inspector uses it to choose which listings to ask (those with real demand) and to read what each listing
states (its price and pay-to). Coinbase's developer terms limit sharing data from its tools, so the published
sheet carries the index's demand counts only when `publish_index_counts` is set (see sheet.py).
"""

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from agoranome_inspector import networks
from agoranome_inspector.canonical import digest
from agoranome_inspector.pick import x402_words
from agoranome_inspector.probe import options

INDEX_URL = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"
REAL_DEMAND_PAYERS = 3   # unique payers in 30 days, the lab's "traction"

# The lab's category rules (key, keyword pattern); the first match wins.
CATEGORIES = [
    ("documents", r"\bpdf\b|\bocr\b|document|invoice|receipt pars"),
    ("media", r"image|video|audio|speech|\btts\b|transcri|voice|photo"),
    ("ai_models", r"\bllm\b|\bgpt|claude|gemini|inference|completion|embedding|\bai model"),
    ("web_search", r"\bsearch|\bserp\b|google|bing"),
    ("page_reading", r"scrap|crawl|markdown|webpage|web page|html|fetch url|extract.*url"),
    ("news", r"\bnews|headline|article"),
    ("market_data", r"\bstock|ticker|forex|ohlc|market data|equit|price feed"),
    ("enrichment", r"enrich|company|contact|\blead|linkedin|whois|person|email (lookup|verif)"),
    ("weather_geo", r"weather|geocod|\bmaps?\b|location|\bip (lookup|geo)"),
    ("chain_data", r"wallet|token|erc-?20|on-?chain|blockchain|defi|\bdex\b|swap|\bnft|\bevm\b|solana|ethereum"
                   r"|\bbase\b|crypto"),
    ("agent_tools", r"\bagent|\bmcp\b|\btool|workflow"),
]
_COMPILED = [(k, re.compile(p)) for k, p in CATEGORIES]


def categorize(service: str, description: str, tags: List[str], resource: str) -> str:
    text = " ".join([service or "", description or "", " ".join(tags or []), resource or ""]).lower()
    for key, pattern in _COMPILED:
        if pattern.search(text):
            return key
    return "other"


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize(item: Dict[str, Any]) -> Dict[str, Any]:
    """One index item, reduced to what the inspector reads."""
    resource = str(item.get("resource") or "").strip()
    if not networks.is_url(resource):
        resource = ""          # not a URL: never on the sheet, so nothing else a seller wrote there is signed
    host = (urlparse(resource).hostname or "").lower()
    quality = item.get("quality") or {}
    tags = [str(t) for t in item.get("tags") or []]
    return {
        "resource": resource,
        "host": host,
        "listed": options(item),
        "payers_30d": _int(quality.get("l30DaysUniquePayers")),
        "calls_30d": _int(quality.get("l30DaysTotalCalls")),
        "category": categorize(str(item.get("serviceName") or host), str(item.get("description") or ""),
                               tags, resource),
        "words": x402_words(item) if resource else [],     # for the fair pick (pick.py): sorted words, no sentences
    }


def has_real_demand(listing: Dict[str, Any], min_payers: int = REAL_DEMAND_PAYERS) -> bool:
    return listing["payers_30d"] >= min_payers


def is_repeat_use(listing: Dict[str, Any]) -> bool:
    return has_real_demand(listing) and listing["calls_30d"] >= 2 * listing["payers_30d"]


class IndexReader:
    """Polite paging through the index, with backoff on 429 and 5xx."""

    def __init__(self, url: str = INDEX_URL, client: Optional[httpx.Client] = None, page_size: int = 100,
                 max_pages: int = 2000, pause: float = 0.25, sleep: Callable[[float], None] = time.sleep):
        self.url = url
        self.client = client or httpx.Client(timeout=30.0, headers={"Accept": "application/json",
                                                                   "User-Agent": "Agoranome-inspector/0.1"})
        self.page_size = page_size
        self.max_pages = max_pages
        self.pause = pause
        self.sleep = sleep

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        delay = 2.0
        for attempt in range(5):
            resp = self.client.get(self.url, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == 4:
                    resp.raise_for_status()
                self.sleep(delay)
                delay *= 2
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("unreachable")

    def read(self) -> Dict[str, Any]:
        """Every http listing in the index, normalized, with the digest of the raw pages."""
        listings: List[Dict[str, Any]] = []
        page_digests = []
        offset, total, pages = 0, None, 0
        while pages < self.max_pages:
            page = self._get({"type": "http", "limit": self.page_size, "offset": offset})
            items = page.get("items") or []
            page_digests.append(digest(json.loads(json.dumps(items), parse_float=str)))
            listings.extend(normalize(i) for i in items if isinstance(i, dict))
            pagination = page.get("pagination") or {}
            total = pagination.get("total", total)
            offset += int(pagination.get("limit") or len(items) or self.page_size)
            pages += 1
            if not items or (total is not None and offset >= int(total)):
                break
            self.sleep(self.pause)
        return {
            "url": self.url,
            "listings": listings,
            "total_reported": int(total) if total is not None else None,
            "complete": total is not None and len(listings) >= int(total),
            "digest": digest(page_digests),
        }


def select(listings: List[Dict[str, Any]], min_payers: int = REAL_DEMAND_PAYERS) -> List[Dict[str, Any]]:
    """The listings with real demand, one per resource (the busiest copy when the index repeats one). A listing
    that is not on https stays in: the probe declines to ask it, and the sheet says so."""
    best: Dict[str, Dict[str, Any]] = {}
    for listing in listings:
        if not listing["resource"] or not has_real_demand(listing, min_payers):
            continue
        kept = best.get(listing["resource"])
        if kept is None or (listing["payers_30d"], listing["calls_30d"]) > (kept["payers_30d"], kept["calls_30d"]):
            best[listing["resource"]] = listing
    return sorted(best.values(), key=lambda x: x["resource"])
