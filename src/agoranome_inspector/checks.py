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

"""The check before signing. The verifier proves a book is consistent, not that a week's reading is sound, and the
book only grows, so a reading that looks broken is held unpublished for the operator instead of being signed.

A sheet is held when:
  - the index was not read completely (short by more than MAX_INDEX_SHORT of what it reports);
  - it has no rows;
  - more than MAX_UNREACHABLE of the endpoints asked gave no HTTP answer at all (the run's network, not the
    sellers, is the likely cause);
  - against the last sheet of the same market, the row count moved by more than MAX_ROWS_MOVE, or the share of
    payable answers moved by more than MAX_PAYABLE_MOVE (percentage points).

The operator can publish a held sheet anyway after looking; the book then carries a note saying so and why.
"""

from typing import Any, Dict, List, Optional

MAX_UNREACHABLE = 0.25
MAX_ROWS_MOVE = 0.30
MAX_PAYABLE_MOVE = 0.10
# The index is live and is paged for minutes, so a listing added meanwhile can be missed (a trial read 32,964 of
# 32,965). A read short by at most this share of the listings the index reports still counts as read.
MAX_INDEX_SHORT = 0.001
# Answers that say nothing about whether the endpoint works: not reached, not public, or (MPP) wanting a request
# the inspector could not form.
NOT_ASKED = ("not_asked", "declined", "wants_input")


def _share(summary: Dict[str, Any], answer: str, of: Optional[int] = None) -> float:
    answers = summary.get("answer") or {}
    total = of if of is not None else sum(answers.values())
    return answers.get(answer, 0) / total if total else 0.0


def _asked(summary: Dict[str, Any]) -> int:
    answers = summary.get("answer") or {}
    return sum(n for k, n in answers.items() if k not in NOT_ASKED)


def before_signing(sheet: Dict[str, Any], previous: Optional[Dict[str, Any]] = None) -> List[str]:
    """Why this sheet should be held, or an empty list. `previous` is the last published sheet of the same market."""
    reasons: List[str] = []
    selection = sheet.get("selection") or {}
    if selection.get("index_complete") is False:
        total, read = selection.get("index_listings"), selection.get("index_read")
        if not (isinstance(total, int) and isinstance(read, int) and total > 0
                and (total - read) / total <= MAX_INDEX_SHORT):
            reasons.append(f"the index was not read completely ({read} of {total} listings)")
    summary = sheet.get("summary") or {}
    rows = summary.get("rows", len(sheet.get("rows") or []))
    if not rows:
        reasons.append("the sheet has no rows")
        return reasons
    asked = _asked(summary)
    unreachable = _share(summary, "unreachable", asked)
    if asked and unreachable > MAX_UNREACHABLE:
        reasons.append(f"{unreachable:.0%} of the endpoints asked gave no answer at all (bound {MAX_UNREACHABLE:.0%})")
    if previous is not None:
        before = previous.get("summary") or {}
        before_rows = before.get("rows", 0)
        if before_rows and abs(rows - before_rows) / before_rows > MAX_ROWS_MOVE:
            reasons.append(f"the row count moved from {before_rows:,} to {rows:,} (bound {MAX_ROWS_MOVE:.0%})")
        now_payable = _share(summary, "payable", _asked(summary))
        then_payable = _share(before, "payable", _asked(before))
        if _asked(before) and abs(now_payable - then_payable) > MAX_PAYABLE_MOVE:
            reasons.append(f"the payable share moved from {then_payable:.1%} to {now_payable:.1%} "
                           f"(bound {MAX_PAYABLE_MOVE * 100:.0f} points)")
    return reasons
