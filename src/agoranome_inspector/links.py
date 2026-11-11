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

"""Operator links: which hosts one operator seems to run, worked out from the published sheets alone.

Two kinds of fact, each with its evidence:

  same_pay_to   hosts whose live offers ask payment to the same address (an x402 pay-to or an MPP recipient). An
                address that more than PLATFORM_HOSTS hosts share is a platform's (a processor's or a facilitator's
                address, say) and links nobody; it is listed with its host count only. Hosts joined by shared
                addresses form one operator (a connected component), as in the lab's market graph.
  same_host     one host selling in more than one market (an x402 row and an MPP row on the same host name).

A link is a fact beside the rows, never a verdict: no row's verdict changes because of it, and a seller is judged
on its own answers. Anyone holding the sheets computes the same file, so the verifier checks it the way it checks a
change log.
"""

from typing import Any, Dict, List, Set

KIND = "agoranome.links"
FORMAT = 1
PLATFORM_HOSTS = 5
SHOWN = 10          # resources named per host in the evidence; the rest are counted

PAY_KEYS = {"x402": "pay_to", "mpp": "recipient"}


def _market(sheet: Dict[str, Any]) -> str:
    return sheet.get("market") or "x402"


def _addresses(row: Dict[str, Any], market: str) -> Set[str]:
    if (row.get("verdict") or {}).get("answer") != "payable":
        return set()
    key = PAY_KEYS.get(market, "pay_to")
    return {o[key] for o in (row.get("seen") or {}).get("options") or [] if o.get(key)}


def build(sheets: List[Dict[str, Any]], links_id: str) -> Dict[str, Any]:
    """The links among the hosts on these sheets (the newest sheet of each market)."""
    by_address: Dict[str, Dict[str, Set[str]]] = {}      # address -> host -> resources
    by_host: Dict[str, Dict[str, List[str]]] = {}        # host -> market -> resources
    for sheet in sheets:
        market = _market(sheet)
        for row in sheet.get("rows") or []:
            host = row["host"]
            by_host.setdefault(host, {}).setdefault(market, []).append(row["resource"])
            for address in _addresses(row, market):
                by_address.setdefault(address, {}).setdefault(host, set()).add(f"{market} {row['resource']}")

    platforms, shared = [], {}
    for address, hosts in sorted(by_address.items()):
        if len(hosts) > PLATFORM_HOSTS:
            platforms.append({"address": address, "hosts": len(hosts)})
        elif len(hosts) > 1:
            shared[address] = hosts

    parent: Dict[str, str] = {}

    def find(h: str) -> str:
        while parent.setdefault(h, h) != h:
            parent[h] = parent[parent[h]]
            h = parent[h]
        return h

    for hosts in shared.values():
        first, *rest = sorted(hosts)
        for other in rest:
            parent[find(other)] = find(first)
    groups: Dict[str, Set[str]] = {}
    for host in parent:
        groups.setdefault(find(host), set()).add(host)

    operators = []
    for members in sorted((sorted(g) for g in groups.values()), key=lambda g: g[0]):
        evidence = []
        for address, hosts in sorted(shared.items()):
            if set(hosts) <= set(members):
                evidence.append({"kind": "same_pay_to", "address": address, "hosts": {
                    h: {"resources": sorted(hosts[h])[:SHOWN], "count": len(hosts[h])} for h in sorted(hosts)}})
        operators.append({"hosts": members, "evidence": evidence})

    cross = [{"kind": "same_host", "host": host,
              "markets": {m: {"resources": sorted(r)[:SHOWN], "count": len(r)} for m, r in sorted(markets.items())}}
             for host, markets in sorted(by_host.items()) if len(markets) > 1]

    return {
        "kind": KIND,
        "format": FORMAT,
        "id": links_id,
        "from": [s["id"] for s in sheets],
        "platform_hosts": PLATFORM_HOSTS,
        "operators": operators,
        "same_host": cross,
        "platform_addresses": platforms,
        "counts": {"operators": len(operators), "linked_hosts": sum(len(o["hosts"]) for o in operators),
                   "same_host": len(cross), "platform_addresses": len(platforms)},
    }
