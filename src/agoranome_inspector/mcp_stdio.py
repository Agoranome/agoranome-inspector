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

"""The inspector as an MCP server on stdin and stdout, with no dependency beyond the package.

  agoranome-inspector mcp [SITE]

Two tools, both free and read-only, both answered from the published site after the open book is checked:

  fair_pick   endpoints for a job and a budget, ranked by the published rule pick-1 (pick.py)
  seller_row  one endpoint's row on the newest sheet, with its Merkle proof against the root the book signed

Messages are JSON-RPC 2.0, one per line (the MCP stdio transport). Nothing a seller wrote reaches the answer as a
sentence: the pick carries addresses, prices, verdicts and sorted words only.
"""

import json
import sys
import time
from typing import Any, Callable, Dict, IO, List, Optional

from agoranome_inspector import __version__
from agoranome_inspector import pick as pick_lib

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
FRESH_SECONDS = 6 * 3600

INSTRUCTIONS = (
    "Agoranome's inspector reads every x402 listing with real demand and every paid MPP endpoint each week, asks "
    "each one unpaid what it charges, and signs the result into an open book anyone can verify. Call fair_pick "
    "with the job in plain words and the most you will pay for one request; it answers with endpoints ranked by "
    "a published rule no seller can pay for: honest on price first, then signs of delivery, then price. Call "
    "seller_row with an endpoint's address before paying it to see its verdict and the proof that the row is on "
    "the signed sheet. Both are free. Nothing here is advice to pay; the price an endpoint asks when you call it "
    "is the price, and your own ceiling should still apply.")

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "fair_pick",
        "title": "Fair pick of paid endpoints",
        "description": (
            "Endpoints that fit a job, ranked by Agoranome's published rule pick-1: only endpoints that gave a "
            "payable offer on this week's sheet and whose words match the job; then those that asked what they "
            "list first, then those that promise to settle only on delivery, then the lower price. No seller can "
            "pay for a place. Free."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job": {"type": "string", "description": "What the endpoint should do, in plain words.",
                        "maxLength": pick_lib.MAX_JOB},
                "budget_usd": {"type": ["number", "string"],
                               "description": "The most to pay for one request, in US dollars (e.g. 0.01)."},
                "market": {"type": "string", "enum": ["x402", "mpp"], "description": "One market only."},
                "limit": {"type": "integer", "minimum": 1, "maximum": pick_lib.MAX_LIMIT, "default": pick_lib.LIMIT},
            },
            "required": ["job"],
            "additionalProperties": False,
        },
        "annotations": {"title": "Fair pick", "readOnlyHint": True, "openWorldHint": True, "idempotentHint": True},
    },
    {
        "name": "seller_row",
        "title": "An endpoint's row on the signed sheet",
        "description": (
            "One paid endpoint's row on the newest weekly sheet: what it lists, what it asked when asked unpaid, "
            "the verdict, and the Merkle proof that the row is on the sheet the open book signed. Free."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "resource": {"type": "string", "description": "The endpoint's address, as listed. For MPP, the "
                                                              "method and the address, e.g. 'POST https://...'."},
            },
            "required": ["resource"],
            "additionalProperties": False,
        },
        "annotations": {"title": "Seller row", "readOnlyHint": True, "openWorldHint": True, "idempotentHint": True},
    },
]


class Inspector:
    """The site's pick tables and sheets, read once and again after FRESH_SECONDS."""

    def __init__(self, site: str, pinned_kid: Optional[str] = None, get: Optional[Callable[[str], bytes]] = None,
                 clock: Callable[[], float] = time.time):
        from agoranome_inspector.verify import http_get

        self.site, self.pinned_kid, self.clock = site, pinned_kid, clock
        self._get = get or http_get
        self._cache: Dict[str, Any] = {}
        self._tables: Optional[List[Dict[str, Any]]] = None
        self._at = 0.0

    def get(self, url: str) -> bytes:
        kept = self._cache.get(url)
        if kept and self.clock() - kept[0] < FRESH_SECONDS:
            return kept[1]
        data = self._get(url)
        self._cache[url] = (self.clock(), data)
        return data

    def tables(self) -> List[Dict[str, Any]]:
        from agoranome_inspector.picking import load_tables

        if self._tables is None or self.clock() - self._at >= FRESH_SECONDS:
            self._tables = load_tables(self.site, pinned_kid=self.pinned_kid, get=self.get)
            self._at = self.clock()
        return self._tables

    def fair_pick(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return pick_lib.rank(self.tables(), args.get("job") or "", args.get("budget_usd"),
                             market=args.get("market"), limit=args.get("limit") or pick_lib.LIMIT)

    def seller_row(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from agoranome_inspector.picking import RAW, SITE
        from agoranome_inspector.verify import proof_for

        resource = str(args.get("resource") or "").strip()
        if not resource:
            raise ValueError("resource is required")
        try:
            return proof_for(self.site, resource, get=self.get)
        except LookupError:
            raise
        except Exception:
            if self.site.rstrip("/") + "/" != SITE:
                raise
            return proof_for(RAW, resource, get=self.get)


def handle(inspector: Inspector, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The answer to one JSON-RPC message, or None for a notification."""
    method, rid = message.get("method"), message.get("id")
    if rid is None:
        return None

    def ok(result: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        return ok({"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "agoranome-inspector", "title": "Agoranome inspector",
                                  "version": __version__},
                   "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        tool = {"fair_pick": inspector.fair_pick, "seller_row": inspector.seller_row}.get(name)
        if tool is None:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"unknown tool {name!r}"}}
        try:
            found = tool(args if isinstance(args, dict) else {})
        except (ValueError, LookupError, RuntimeError) as e:
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
        return ok({"content": [{"type": "text", "text": json.dumps(found, indent=1)}], "structuredContent": found,
                   "isError": False})
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"no method {method!r}"}}


def serve(site: str, *, pinned_kid: Optional[str] = None, stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout,
          inspector: Optional[Inspector] = None) -> None:
    inspector = inspector or Inspector(site, pinned_kid)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            answer: Optional[Dict[str, Any]] = {"jsonrpc": "2.0", "id": None,
                                                "error": {"code": -32700, "message": "not JSON"}}
        else:
            answer = handle(inspector, message) if isinstance(message, dict) else {
                "jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "not a request"}}
        if answer is not None:
            stdout.write(json.dumps(answer) + "\n")
            stdout.flush()
