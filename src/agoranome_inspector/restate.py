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

"""A restatement: a published sheet judged again under a newer rule, beside the original, never instead of it.

The original sheet stays in the book and on the site, and still verifies under its own rule. A restatement is a
file computed from that sheet alone (each row's listing and answer, judged again under the new rule), so anyone
holding the sheet rebuilds it byte for byte, and the verifier does. It holds the counts before and after, the
headline (how many listings differ from their listing), every row whose judged verdict (answer, price, pay-to or
match) changed with both verdicts, and in plain words why the rule changed.
"""

from typing import Any, Dict, List

from agoranome_inspector import sheet as sheet_lib
from agoranome_inspector.canonical import canonical
from agoranome_inspector.merkle import leaf_hash
from agoranome_inspector.rules import METHODS, RULES

KIND = "agoranome.restatement"
FORMAT = 1
# What a row's verdict says about the seller. A newer rule may add fields (sheet-2's floating); a row is changed when
# one of these is.
JUDGED = ("answer", "price", "pay_to", "matches_listing")

# Why a sheet judged by one rule is judged again by another, in words, for each pair a restatement is made for.
WHY = {
    ("sheet-1", "sheet-2"): (
        "Sheet-1 compared each listed and live amount in the asset's own units. A seller who prices in dollars and "
        "quotes XRP or another floating token at the day's rate was counted above its listing whenever the index "
        "was a few days old, and more than half of the listings this sheet counted as differing were that drift, "
        "not a higher price. Sheet-2 judges price on dollar options only (USDC on ten networks, by contract), "
        "reports every other option's price apart as floating, and holds a different pay-to address against a "
        "seller on any option, since an address does not drift. The original sheet is unchanged and still "
        "verifies under sheet-1."
    ),
}


def flagged(summary: Dict[str, Any]) -> int:
    """The headline: listings whose live offer differs from their listing (matches_listing false)."""
    return int((summary.get("matches_listing") or {}).get("false", 0))


def _share(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "0.0%"


def build(sheet: Dict[str, Any], rule: str) -> Dict[str, Any]:
    """The restatement of a published sheet under `rule`."""
    old_rule = sheet.get("rule")
    if rule not in RULES:
        raise ValueError(f"unknown rule {rule!r}")
    if (old_rule, rule) not in WHY:
        raise ValueError(f"no restatement from {old_rule} to {rule} is written")
    judge = RULES[rule]
    rows = sheet["rows"]
    after_rows: List[Dict[str, Any]] = [{**r, "verdict": judge(r.get("listed") or [], r.get("seen"))} for r in rows]
    changed = [{"resource": r["resource"], "host": r["host"], "leaf": leaf_hash(r), "before": r["verdict"],
                "after": a["verdict"]}
               for r, a in zip(rows, after_rows)
               if any(a["verdict"].get(k) != r["verdict"].get(k) for k in JUDGED)]
    before, after = sheet_lib.summarize(rows), sheet_lib.summarize(after_rows)
    n = len(rows)
    moved: Dict[str, int] = {}
    for c in changed:
        key = f"{_name(c['before'].get('matches_listing'))}->{_name(c['after'].get('matches_listing'))}"
        moved[key] = moved.get(key, 0) + 1
    return {
        "kind": KIND,
        "format": FORMAT,
        "market": sheet_lib.market_of(sheet),
        "sheet": sheet["id"],
        "rule": {"from": old_rule, "to": rule},
        "why": WHY[(old_rule, rule)],
        "method": METHODS[rule],
        "headline": {
            "rows": n,
            "before": {"differ": flagged(before), "share": _share(flagged(before), n)},
            "after": {"differ": flagged(after), "share": _share(flagged(after), n)},
        },
        "summary": {"before": before, "after": after},
        "moved": dict(sorted(moved.items())),
        "changed": changed,
    }


def _name(value: Any) -> str:
    return "null" if value is None else str(value).lower()


def to_bytes(restatement: Dict[str, Any]) -> bytes:
    return canonical(restatement) + b"\n"


def file_for(sheet_id: str, rule: str) -> str:
    return f"restatements/{sheet_id}.{rule}.json"


def check(data: bytes, sheet: Dict[str, Any], body: Dict[str, Any]) -> List[str]:
    """Problems with a published restatement, given the sheet it names (already checked against the book)."""
    rule = (body.get("rule") or {}).get("to")
    try:
        rebuilt = build(sheet, rule)
    except (ValueError, KeyError) as e:
        return [f"cannot be rebuilt ({e})"]
    problems = []
    if data != to_bytes(rebuilt):
        problems.append("the file is not the one rebuilt from the sheet")
    if body.get("headline") != rebuilt["headline"]:
        problems.append("the book's headline does not match the sheet judged again")
    if body.get("summary") != rebuilt["summary"]["after"]:
        problems.append("the book's summary does not match the sheet judged again")
    if body.get("changed") != len(rebuilt["changed"]):
        problems.append("the book's count of changed rows does not match")
    return problems
