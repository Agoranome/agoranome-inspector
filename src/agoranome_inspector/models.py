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

"""Model calls, under a hard monthly cap.

Where models are used (the weekly note, the run doctor, the monthly red-team of this code, the weekly buyer test
of Agoranome's own listings and the one-off verdict study) and what they may not do:

  - No model decides a verdict, sits in the publishing path, or reads sellers' words. The sheet, its change log
    and the book are built, signed, verified and pushed before any model is asked, and a model's text is never
    signed into the book.
  - Every call may fail and nothing else does: `ask` returns None on a missing key, a missing SDK, an API error,
    a refusal, a cut-off answer, or a call that could take the month past the cap.

The cap is kept in an append-only spend ledger (JSON Lines, one line per reservation and per settlement). Before
a call, its worst case is reserved: the counted input tokens at the highest input price any model it may be
served by charges, plus max_tokens at the highest output price. A call whose worst case would take the month's
spend past the cap is not made. After the call, the reservation is settled at the cost of the usage returned;
a call that failed stays reserved at its worst case, since it may have been billed. With no ledger, no call is
made, and a missing or damaged ledger file is no ledger. The cap can be lowered with INSPECTOR_MODEL_CAP_USD, never raised above CAP_USD.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CAP_USD = 20.0
DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# US dollars per million tokens (input, output), from Anthropic's price list as read on 11 Nov 2026. A model not
# listed here is priced at the highest prices listed.
PRICES = {
    "claude-fable-5-2": (8.00, 40.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
CACHE_WRITE = 2.0       # no call here caches; if one did, a write costs at most twice the input price
WORST_IN = max(p[0] for p in PRICES.values())
WORST_OUT = max(p[1] for p in PRICES.values())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def model() -> str:
    return os.environ.get("INSPECTOR_MODEL") or DEFAULT_MODEL


def cap() -> float:
    try:
        asked = float(os.environ.get("INSPECTOR_MODEL_CAP_USD") or CAP_USD)
    except ValueError:
        asked = CAP_USD
    return max(0.0, min(asked, CAP_USD))


def worst_case(input_tokens: int, max_tokens: int) -> float:
    """The most a call can cost, whichever model serves it (with a quarter more input than counted, for what the
    API adds to a request)."""
    return (input_tokens * 1.25 * WORST_IN + max_tokens * WORST_OUT) / 1_000_000


def cost(usage: Any, served_by: Optional[str]) -> float:
    """What a call's usage costs at the prices of the model that served it."""
    price_in, price_out = PRICES.get(served_by or "", (WORST_IN, WORST_OUT))

    def n(name: str) -> int:
        value = getattr(usage, name, None) if not isinstance(usage, dict) else usage.get(name)
        return int(value or 0)

    tokens_in = n("input_tokens") + n("cache_creation_input_tokens") * CACHE_WRITE + n("cache_read_input_tokens") * 0.1
    return (tokens_in * price_in + n("output_tokens") * price_out) / 1_000_000


class Ledger:
    """The month's model spend, as an append-only JSON Lines file that git can merge (merge=union)."""

    def __init__(self, path: str):
        self.path = Path(path)

    def _lines(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))      # a damaged ledger raises, and the caller makes no call
        return out

    def spent(self, month: Optional[str] = None) -> float:
        month = month or _now().strftime("%Y-%m")
        calls: Dict[str, float] = {}
        settled: Dict[str, float] = {}
        for entry in self._lines():
            if entry.get("month") != month:
                continue
            target = settled if entry.get("state") == "settled" else calls
            target[entry["call"]] = float(entry["usd"])
        return sum(settled.get(call, usd) for call, usd in calls.items()) + sum(
            usd for call, usd in settled.items() if call not in calls)

    def add(self, entry: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())


def _say(text: str) -> None:
    print(f"model: {text}", file=sys.stderr)


def _client():
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic(max_retries=2, timeout=900.0)


def ask(use: str, system: str, user: str, *, max_tokens: int, effort: str = "medium", stream: bool = False,
        output_format: Optional[Dict[str, Any]] = None, client: Any = None,
        ledger: Optional[Ledger] = None) -> Optional[str]:
    """One model call within the month's cap: its text answer, or None if no call was made or it gave nothing
    usable. Never raises."""
    try:
        if ledger is None:
            path = os.environ.get("INSPECTOR_SPEND_LEDGER")
            if not path:
                _say(f"{use}: no spend ledger (INSPECTOR_SPEND_LEDGER), so no call")
                return None
            ledger = Ledger(path)
        if not ledger.path.exists():
            _say(f"{use}: the spend ledger {ledger.path} was not read, so no call")
            return None
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                _say(f"{use}: no ANTHROPIC_API_KEY, so no call")
                return None
            client = _client()
            if client is None:
                _say(f"{use}: the anthropic package is not installed, so no call")
                return None
        name = model()
        messages = [{"role": "user", "content": user}]
        counted = client.messages.count_tokens(model=name, system=system, messages=messages).input_tokens
        worst = worst_case(int(counted), max_tokens)
        month = _now().strftime("%Y-%m")
        spent = ledger.spent(month)
        if spent + worst > cap():
            _say(f"{use}: the worst case ${worst:.2f} would take {month} past the ${cap():.2f} cap "
                 f"(${spent:.2f} spent), so no call")
            return None
        call = uuid.uuid4().hex
        stamp = {"call": call, "month": month, "use": use, "model": name}
        ledger.add({**stamp, "state": "reserved", "usd": round(worst, 6), "at": _now().isoformat()})
        kwargs: Dict[str, Any] = {
            "model": name, "max_tokens": max_tokens, "system": system, "messages": messages,
            "output_config": {"effort": effort, **({"format": output_format} if output_format else {})},
            "betas": [FALLBACK_BETA], "fallbacks": "default",
        }
        try:
            if stream:
                with client.beta.messages.stream(**kwargs) as s:
                    message = s.get_final_message()
            else:
                message = client.beta.messages.create(**kwargs)
        except Exception as e:  # noqa: BLE001 - the reservation stands; the caller goes on without a model
            _say(f"{use}: the call failed ({type(e).__name__}); its worst case stays reserved")
            return None
        served = getattr(message, "model", None) or name
        usd = cost(message.usage, served)
        ledger.add({**stamp, "state": "settled", "usd": round(usd, 6), "served_by": served,
                    "input_tokens": int(getattr(message.usage, "input_tokens", 0) or 0),
                    "output_tokens": int(getattr(message.usage, "output_tokens", 0) or 0),
                    "at": _now().isoformat()})
        _say(f"{use}: ${usd:.4f} on {served}; {month} now ${ledger.spent(month):.2f} of ${cap():.2f}")
        if message.stop_reason in ("refusal", "max_tokens"):
            _say(f"{use}: the answer stopped ({message.stop_reason}), so it is not used")
            return None
        text = "".join(getattr(b, "text", "") for b in message.content if getattr(b, "type", "") == "text").strip()
        return text or None
    except Exception as e:  # noqa: BLE001 - no model failure may reach the caller
        _say(f"{use}: no answer ({type(e).__name__})")
        return None
