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

"""The change log: what changed between two published sheets, computed from the two sheets alone.

Free and public, where the lab sold it as a $1 watch. Anyone holding both sheets computes the same log, so the
verifier checks it the same way it checks a sheet.

Kinds of change, for a listing on both sheets:
  price_cut, price_raised      the live asked amount on the same network and asset went down or up
  listed_price_changed         the listing's own stated amount changed
  pay_to_changed               the live pay-to address of the compared option changed
  went_dark, came_back         the answer went from payable to anything else, or back
  verdict_changed              the price or pay-to verdict changed (for example as_listed to above_listed)
and for a listing on one sheet only:
  joined, left                 it reached real demand (or was first asked), or it dropped off the sheet
"""

from typing import Any, Dict, List, Optional

KIND = "agoranome.x402-changes"
FORMAT = 1


def _by_resource(sheet: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {r["resource"]: r for r in sheet["rows"]}


# The keys that name where an option is paid, in what, and to whom, in each market.
KEYS = {"x402": ("network", "asset", "pay_to"), "mpp": ("method", "currency", "recipient")}


def _first_listed(r: Dict[str, Any], net: str, asset: str) -> Optional[Dict[str, Any]]:
    listed = [o for o in r.get("listed") or [] if o.get(net) and o.get(asset) and o.get("amount")]
    return listed[0] if listed else None


def _change(resource: str, host: str, kind: str, before: Any, after: Any) -> Dict[str, Any]:
    return {"resource": resource, "host": host, "kind": kind, "before": before, "after": after}


def diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    old, new = _by_resource(before), _by_resource(after)
    net, asset, pay = KEYS.get(after.get("market") or "x402", KEYS["x402"])
    found: List[Dict[str, Any]] = []
    for resource in sorted(set(old) | set(new)):
        a, b = old.get(resource), new.get(resource)
        if a is None:
            found.append(_change(resource, b["host"], "joined", None, b["verdict"]["answer"]))
            continue
        if b is None:
            found.append(_change(resource, a["host"], "left", a["verdict"]["answer"], None))
            continue
        host = b["host"]
        va, vb = a["verdict"], b["verdict"]
        if va["answer"] == "payable" and vb["answer"] != "payable":
            found.append(_change(resource, host, "went_dark", va["answer"], vb["answer"]))
        elif va["answer"] != "payable" and vb["answer"] == "payable":
            found.append(_change(resource, host, "came_back", va["answer"], vb["answer"]))
        la, lb = _first_listed(a, net, asset), _first_listed(b, net, asset)
        if la and lb and (la[net], la[asset]) == (lb[net], lb[asset]) and la["amount"] != lb["amount"]:
            found.append(_change(resource, host, "listed_price_changed", la["amount"], lb["amount"]))
        aa, ab = va.get("asked"), vb.get("asked")
        if aa and ab and (aa.get(net), aa.get(asset)) == (ab.get(net), ab.get(asset)):
            if int(ab["amount"]) < int(aa["amount"]):
                found.append(_change(resource, host, "price_cut", aa["amount"], ab["amount"]))
            elif int(ab["amount"]) > int(aa["amount"]):
                found.append(_change(resource, host, "price_raised", aa["amount"], ab["amount"]))
            if aa.get(pay) != ab.get(pay):
                found.append(_change(resource, host, "pay_to_changed", aa.get(pay), ab.get(pay)))
        for key in ("price", "pay_to"):
            if va.get(key) and vb.get(key) and va[key] != vb[key]:
                found.append(_change(resource, host, "verdict_changed",
                                     {key: va[key]}, {key: vb[key]}))
    counts: Dict[str, int] = {}
    for change in found:
        counts[change["kind"]] = counts.get(change["kind"], 0) + 1
    return {
        "kind": KIND,
        "format": FORMAT,
        "market": after.get("market") or "x402",
        "from": before["id"],
        "to": after["id"],
        "changes": found,
        "counts": dict(sorted(counts.items())),
    }
