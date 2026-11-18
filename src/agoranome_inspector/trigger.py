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

"""The market count that reopens Agoranome's wider build (`trigger` entries, rule reopen-1).

Shariar's decision of 18 Nov 2026 (the validation's item C7): the wider build reopens once 50 x402 hosts each have 25
or more repeat payers, counted by the Inspector so nobody has to argue it. The count is read from the newest signs
file (signs.py, rule signs-1): a host counts when its pay-to addresses were all read from the chain (state "counted")
and 25 or more of its payers, none of them the host's own addresses, paid it in more than one session within the
window (30 days). Nothing here reads the chain or the network: the verifier counts again from the same signed file.

Each new signs file gets one entry: the count, whether it meets the bar, how many distinct sellers those hosts are
under the seller rule pick-2 uses (sellers.py: shown beside the count, never part of the bar), and the first signs
reading that met it, carried forward so a later dip below the bar does not hide that the bar was met. The signs file
reads at most a few hundred hosts, the busiest first, so a count under the bar is a floor, not the market.
"""

from typing import Any, Callable, Dict, List, Optional

from agoranome_inspector import sellers
from agoranome_inspector import signs as signs_lib
from agoranome_inspector.canonical import sha256_hex

RULE = "reopen-1"
MIN_REPEAT = 25
HOSTS_NEEDED = 50
DECIDED = "2026-11-18"
TEXT = (f"The wider build reopens once {HOSTS_NEEDED} x402 hosts each have {MIN_REPEAT} or more repeat payers in the "
        f"newest delivery signs (rule {signs_lib.RULE}: payers who paid the host in more than one session within "
        f"the window, the host's own addresses left out).")


def count(found: Dict[str, Any]) -> Dict[str, Any]:
    """The hosts of a signs file that meet the bar, and the sellers they are."""
    meeting = sorted(h["host"] for h in signs_lib.by_host(found).values()
                     if int(h.get("repeat_payers") or 0) >= MIN_REPEAT)
    pairs = [(h["host"], a) for h in (found.get("hosts") or []) if h.get("host") in meeting
             for a in h.get("pay_to") or []]
    named = sellers.seller_of(pairs, lambda p: p[0], lambda p: p[1])
    totals = found.get("totals") or {}
    return {"hosts": len(meeting), "sellers": len({named.get(h, h) for h in meeting}), "meeting": meeting,
            "counted": int(totals.get("counted") or 0), "complete": bool(found.get("complete"))}


def body_for(signs_entry: Dict[str, Any], found: Dict[str, Any], earlier: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The entry for one signs reading, given the trigger entries before it."""
    s = signs_entry["body"]
    got = count(found)
    met = got["hosts"] >= HOSTS_NEEDED
    first = next((e["body"]["first_met"] for e in reversed(earlier) if e["body"].get("first_met")), None)
    reading = {"seq": signs_entry["seq"], "sheet": (s.get("sheet") or {}).get("id")}
    return {"rule": RULE, "decided": DECIDED, "text": TEXT, "min_repeat_payers": MIN_REPEAT,
            "hosts_needed": HOSTS_NEEDED,
            "signs": {**reading, "file": s.get("file"), "sha256": s.get("sha256"), "window": s.get("window")},
            **got, "met": met, "first_met": first or (reading if met else None)}


def check(entry: Dict[str, Any], entries: List[Dict[str, Any]], read: Callable[[str], bytes]) -> List[str]:
    """Count one trigger entry again from the signs file it names and the trigger entries before it."""
    body = entry["body"]
    if body.get("rule") != RULE:
        return [f"unknown trigger rule {body.get('rule')!r}"]
    ref = body.get("signs") or {}
    signs_entry = next((e for e in entries if e["seq"] == ref.get("seq")), None)
    if signs_entry is None or signs_entry["kind"] != "signs" or signs_entry["seq"] >= entry["seq"]:
        return [f"the count names signs entry {ref.get('seq')}, which the book lacks before it"]
    if signs_entry["body"].get("file") != ref.get("file") or signs_entry["body"].get("sha256") != ref.get("sha256"):
        return ["the count names a signs file the signs entry does not"]
    try:
        data = read(ref["file"])
    except Exception as e:   # noqa: BLE001 - reported, never raised
        return [f"could not read {ref.get('file')} ({type(e).__name__})"]
    if sha256_hex(data) != ref.get("sha256"):
        return [f"{ref.get('file')} does not match the hash in the book"]
    earlier = [e for e in entries if e["kind"] == "trigger" and e["seq"] < entry["seq"]]
    if body_for(signs_entry, signs_lib.load(data), earlier) != body:
        return ["the count does not follow from its signs file"]
    return []


def newest(entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    found = [e for e in entries if e["kind"] == "trigger"]
    return found[-1] if found else None
