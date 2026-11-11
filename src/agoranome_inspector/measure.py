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

"""One run of the measurer: read the index, choose the listings with real demand, ask each one unpaid.

Politeness: one request at a time to any host, a pause between a host's listings, at most `per_host` listings
of a host (its busiest first), hosts in order of demand, and a time budget for the whole run. A listing the run
did not reach is kept as not asked, never dropped, so the sheet says how much of the market it covers.

The run file this writes is private: it holds the index's demand counts, which the published sheet leaves out
unless told otherwise (see bazaar.py).
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from agoranome_inspector.bazaar import IndexReader, REAL_DEMAND_PAYERS, select
from agoranome_inspector.fetch import SafeFetcher
from agoranome_inspector.probe import probe

logger = logging.getLogger("inspector.measure")

RUN_KIND = "agoranome.x402-run"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Settings:
    concurrency: int = 16          # hosts asked at the same time
    per_host: int = 100            # listings of one host asked in one run, busiest first
    host_pause: float = 0.5        # seconds between two requests to the same host
    budget_seconds: float = 3 * 3600
    retry_pause: float = 2.0
    min_payers: int = REAL_DEMAND_PAYERS


def ask_all(listings: List[Dict[str, Any]], fetcher: SafeFetcher, settings: Settings,
            sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic,
            clock: Callable[[], str] = _now) -> Dict[str, Dict[str, Any]]:
    """Ask every listing it can within the budget; returns what each answered, keyed by resource."""
    by_host: Dict[str, List[Dict[str, Any]]] = {}
    for listing in listings:
        by_host.setdefault(listing["host"], []).append(listing)
    order = sorted(by_host, key=lambda h: (-sum(x["payers_30d"] for x in by_host[h]), h))
    deadline = monotonic() + settings.budget_seconds
    seen: Dict[str, Dict[str, Any]] = {}

    def one_host(host: str) -> None:
        mine = sorted(by_host[host], key=lambda x: (-x["payers_30d"], -x["calls_30d"], x["resource"]))
        for i, listing in enumerate(mine[: settings.per_host]):
            if monotonic() >= deadline:
                return
            if i:
                sleep(settings.host_pause)
            try:
                seen[listing["resource"]] = probe(fetcher, listing["resource"], retry_pause=settings.retry_pause,
                                                  sleep=sleep, clock=clock)
            except Exception as e:   # one listing lost must not stop the host's others
                logger.warning(f"probe of {listing['resource']} failed: {type(e).__name__}")

    with ThreadPoolExecutor(max_workers=max(1, settings.concurrency)) as pool:
        list(pool.map(one_host, order))
    return seen


def run(run_id: Optional[str] = None, *, reader: Optional[IndexReader] = None,
        fetcher: Optional[SafeFetcher] = None, settings: Optional[Settings] = None,
        clock: Callable[[], str] = _now) -> Dict[str, Any]:
    """Read the index, choose, ask. The result is the private run file."""
    settings = settings or Settings()
    reader = reader or IndexReader()
    fetcher = fetcher or SafeFetcher()
    read_at = clock()
    index = reader.read()
    chosen = select(index["listings"], settings.min_payers)
    started = clock()
    seen = ask_all(chosen, fetcher, settings, clock=clock)
    ended = clock()
    return {
        "kind": RUN_KIND,
        "id": run_id or started[:10],
        "index": {"url": index["url"], "read_at": read_at, "total_reported": index["total_reported"],
                  "complete": index["complete"], "digest": index["digest"], "listings": len(index["listings"])},
        "probe": {"started": started, "ended": ended, "user_agent": fetcher.user_agent,
                  "per_host": settings.per_host, "budget_seconds": int(settings.budget_seconds),
                  "asked": len(seen), "chosen": len(chosen)},
        "listings": chosen,
        "seen": seen,
    }
