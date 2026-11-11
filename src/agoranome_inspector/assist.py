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

"""What models do beside the inspector, each after the sheet is published and never in its way.

  weekly note   A short plain-language note on the week, written from the counts the signed book holds (no row,
                no host, no seller's text is shown to the model). Code then checks that every number in the note
                is one of those counts; a note that fails is dropped. It is written to notes/, outside the book.
  run doctor    When the weekly run is held or fails, an issue with the facts (the held reasons and the log's
                tail), and a model's reading of them when a model answers.
  red-team      Once a month, the inspector's own code is read by a model for ways a seller, a network or a
                mistake could make a sheet wrong or the run unsafe. The findings are encrypted to the inspector's
                signing key before they go into a public issue; `agoranome-inspector reveal` reads them.

Every model call goes through models.ask, under the month's cap. Without a model, the note and the red-team are
skipped and the doctor's issue carries the facts alone.
"""

import base64
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from agoranome_inspector import models
from agoranome_inspector.book import Book, entries_of
from agoranome_inspector.checks import NOT_ASKED
from agoranome_inspector.sheet import market_of

BOOK = "book.jsonl"


# --- The weekly note ---------------------------------------------------------------------------------------------

def facts(site_dir: str) -> Dict[str, Any]:
    """The counts the note may use: the newest sheet of each market, its change log and the newest links, all
    read from the signed book."""
    entries = Book(str(Path(site_dir) / BOOK)).entries()
    newest: Dict[str, Dict[str, Any]] = {}
    for e in entries_of("sheet", entries):
        newest[market_of(e["body"])] = e
    out: Dict[str, Any] = {"markets": {}}
    for market, e in sorted(newest.items()):
        body = e["body"]
        s = body["summary"]
        answers = s.get("answer") or {}
        asked = sum(n for k, n in answers.items() if k not in NOT_ASKED)
        price = s.get("price") or {}
        judged = sum(n for k, n in price.items() if k != "null")
        log = [c for c in entries_of("changes", entries) if c["body"].get("to") == body["id"]]
        out["markets"][market] = {
            "sheet": body["id"],
            "rows": s.get("rows", 0),
            "sellers": s.get("hosts", 0),
            "answers": answers,
            "payable_share_of_asked": f"{answers.get('payable', 0) / asked:.1%}" if asked else None,
            "price": price,
            "price_as_listed_share_of_judged": f"{price.get('as_listed', 0) / judged:.1%}" if judged else None,
            "pay_to": s.get("pay_to") or {},
            "changes_since": log[-1]["body"]["from"] if log else None,
            "changes": log[-1]["body"]["counts"] if log else None,
        }
    links = entries_of("links", entries)
    if links:
        out["operator_links"] = links[-1]["body"]["counts"]
    return out


def _numbers(value: Any, into: Set[str]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _numbers(k, into)
            _numbers(v, into)
    elif isinstance(value, list):
        for v in value:
            _numbers(v, into)
    elif isinstance(value, int):
        into.update({str(value), f"{value:,}"})
    elif isinstance(value, str):
        for found in NUMBER.findall(value):
            into.add(found)
            into.add(found.rstrip("%"))


NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def unchecked_numbers(text: str, source: Dict[str, Any]) -> List[str]:
    """Numbers in `text` that are not among the counts (and dates) in `source`."""
    allowed: Set[str] = set()
    _numbers(source, allowed)
    allowed.update(str(n) for n in range(0, 11))       # small words ("two markets", "one seller") written as digits
    allowed.add("x402")
    out = []
    for found in NUMBER.findall(text):
        word = found.rstrip(",.")
        if word not in allowed and word.rstrip("%") not in allowed:
            out.append(word)
    return out


NOTE_SYSTEM = """You write the weekly note of Agoranome's open sheet, a public inspector of machine-payment
markets (x402, and MPP when present). Each week it asks every listing with real demand for its offer without
paying and says, under a published rule, whether the live offer matches the listing.

You are given only counts from the signed sheets, in JSON. Write the note for a reader who builds or runs agents:
100 to 180 words, plain English, no headings, no lists, no markdown. Say what the week shows and what changed
since the last sheet. Use only numbers that appear in the JSON, written exactly as they appear there (you may add
thousands separators); do not compute new numbers or percentages. Name no seller, give no advice to buy or avoid
anything, and do not guess at reasons the counts do not show. If a count is missing, leave the topic out."""


def weekly_note(site_dir: str, *, ask: Callable[..., Optional[str]] = models.ask,
                now: Optional[datetime] = None) -> Optional[Path]:
    """Write notes/<newest sheet id>.md, once per newest sheet, or nothing. Returns the file written."""
    site = Path(site_dir)
    if not (site / BOOK).exists():
        return None
    found = facts(site_dir)
    if not found["markets"]:
        return None
    newest = entries_of("sheet", Book(str(site / BOOK)).entries())[-1]["body"]["id"]
    if (site / "notes" / f"{newest}.md").exists():
        return None                                     # this week's note is written; nothing new was published
    text = ask("weekly-note", NOTE_SYSTEM, json.dumps(found, indent=1, sort_keys=True), max_tokens=8000,
               effort="low")
    if not text:
        return None
    bad = unchecked_numbers(text, found)
    if bad:
        print(f"weekly note dropped: {len(bad)} number(s) not among the counts", flush=True)
        return None
    sheets = [m["sheet"] for m in found["markets"].values()]
    path = site / "notes" / f"{newest}.md"
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# The week of {day}\n\n{text.strip()}\n\n---\n\n"
        f"Written by a model ({models.model()}) from the counts in the signed sheets {', '.join(sheets)}, and "
        "checked by code so that every number in it is one of those counts. It is not part of the signed book and "
        "decides nothing: the sheets are the record.\n\nThe counts it was given:\n\n```json\n"
        + json.dumps(found, indent=1, sort_keys=True) + "\n```\n")
    return path


# --- The run doctor ----------------------------------------------------------------------------------------------

DOCTOR_SYSTEM = """You help the operator of Agoranome's inspector, a weekly GitHub Actions job that reads the x402
Bazaar index (and the MPP catalog), asks each listing for its payment offer without paying, signs a sheet into an
open book and publishes it to GitHub Pages. This week's run was held by the check before signing, or failed.

You are given the held reasons, if any, and the end of the job's log. Say in under 200 words what most likely
happened and what the operator should check first, most likely cause first. Say plainly when the log does not
show the cause. The check before signing holds a sheet when the index was not read completely, the sheet has no
rows, over 25% of endpoints gave no answer, or rows or the payable share moved too far against last week; a
manual run with "publish anyway" publishes a held sheet after the operator has looked. Plain text, no headings."""


def _tail(text: str, lines: int = 200, chars: int = 20_000) -> str:
    return "\n".join(text.splitlines()[-lines:])[-chars:]


def held_reasons(log: str) -> List[str]:
    out = []
    for line in log.splitlines():
        line = line.strip()
        if line.startswith("{") and '"held"' in line:
            try:
                out.extend(json.loads(line).get("held") or [])
            except ValueError:
                continue
    return out


def doctor_issue(log: str, run_url: Optional[str], *, ask: Callable[..., Optional[str]] = models.ask,
                 day: Optional[str] = None) -> Dict[str, str]:
    """The issue the doctor opens: the facts, and a model's reading when one answers."""
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reasons = held_reasons(log)
    tail = _tail(log)
    title = f"Weekly run {'held' if reasons else 'failed'} on {day}"
    facts_text = json.dumps({"held_reasons": reasons, "run": run_url}, indent=1) + "\n\nEnd of the log:\n" + tail
    reading = ask("run-doctor", DOCTOR_SYSTEM, facts_text, max_tokens=16000, effort="medium")
    body = [f"The weekly run {'was held by the check before signing' if reasons else 'failed'}."
            + (f" [The run]({run_url})." if run_url else "")]
    if reasons:
        body.append("Held because:\n" + "\n".join(f"- {r}" for r in reasons))
        body.append("Nothing held was published. After looking, start **Weekly sheet** by hand with "
                    "*publish anyway* to publish it; the book will say so.")
    body.append("<details><summary>End of the log</summary>\n\n```text\n" + tail.replace("```", "'''")
                + "\n```\n</details>")
    if reading:
        body.append(f"### A model's reading ({models.model()})\n\nNot checked by code; the log above is the "
                    "record.\n\n" + reading)
    else:
        body.append("_No model reading this time (no key, the month's cap, or no answer)._")
    return {"title": title, "body": "\n\n".join(body)}


# --- The monthly red-team ----------------------------------------------------------------------------------------

RED_TEAM_SYSTEM = """You red-team the code of Agoranome's inspector. It reads the x402 Bazaar index and the MPP
catalog, asks each listed endpoint for its payment offer without paying (the endpoints are run by sellers who may
be hostile), judges each answer under a published rule, signs the sheet into a hash-chained, Ed25519-signed open
book, and publishes it with GitHub Actions to GitHub Pages. Anyone can verify the book with one command.

Find the ways a seller, a network, the index, a GitHub workflow or a plain mistake could make a published sheet
wrong or unfair to a seller, hide a mismatch, make the verifier pass on a book it should fail, leak a secret or
the private run file, or harm the machine that runs it. Report only findings you can point to in the code, each
with its severity (high: a sheet or the book can be made wrong, or a secret leaks; medium: possible with an unusual
answer or setup; low: hardening), the file, what goes wrong, and the smallest fix. No style remarks."""

FINDINGS_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                        "title": {"type": "string"},
                        "file": {"type": "string"},
                        "what_goes_wrong": {"type": "string"},
                        "fix": {"type": "string"},
                    },
                    "required": ["severity", "title", "file", "what_goes_wrong", "fix"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["findings"],
        "additionalProperties": False,
    },
}

CODE_GLOBS = ("src/agoranome_inspector/*.py", "scripts/*.py", "scripts/*.sh", ".github/workflows/*.yml",
              "pyproject.toml")
MAX_CODE = 600_000


def code_bundle(repo_dir: str) -> str:
    root = Path(repo_dir)
    parts, size = [], 0
    for pattern in CODE_GLOBS:
        for path in sorted(root.glob(pattern)):
            text = path.read_text(errors="replace")
            if size + len(text) > MAX_CODE:
                break
            parts.append(f'<file path="{path.relative_to(root)}">\n{text}\n</file>')
            size += len(text)
    return "\n".join(parts)


def red_team(repo_dir: str, *, ask: Callable[..., Optional[str]] = models.ask) -> Optional[List[Dict[str, str]]]:
    text = ask("red-team", RED_TEAM_SYSTEM, code_bundle(repo_dir), max_tokens=64000, effort="high", stream=True,
               output_format=FINDINGS_FORMAT)
    if not text:
        return None
    try:
        found = json.loads(text).get("findings")
    except ValueError:
        return None
    return [f for f in found if isinstance(f, dict)] if isinstance(found, list) else None


def report_text(findings: List[Dict[str, str]], day: str) -> str:
    order = {"high": 0, "medium": 1, "low": 2}
    lines = [f"Red-team of the inspector's code, {day}, by {models.model()}. Not checked by code.\n"]
    for i, f in enumerate(sorted(findings, key=lambda f: order.get(f.get("severity"), 3)), 1):
        lines.append(f"{i}. [{f.get('severity')}] {f.get('title')} ({f.get('file')})\n"
                     f"   What goes wrong: {f.get('what_goes_wrong')}\n   Fix: {f.get('fix')}\n")
    return "\n".join(lines)


# The findings are sealed with AES-256-GCM under a key derived (HKDF-SHA256) from the inspector's Ed25519 signing
# key, which only the runner (as a secret) and the operator (as a file) hold.
SEAL_INFO = b"agoranome red-team report v1"
BEGIN, END = "-----BEGIN AGORANOME SEALED REPORT-----", "-----END AGORANOME SEALED REPORT-----"


def _seal_key(signer) -> bytes:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    raw = signer.private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                       serialization.NoEncryption())
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=SEAL_INFO).derive(raw)


def seal(text: str, signer) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    sealed = nonce + AESGCM(_seal_key(signer)).encrypt(nonce, text.encode("utf-8"), SEAL_INFO)
    b64 = base64.b64encode(sealed).decode()
    return "\n".join([BEGIN, *[b64[i:i + 76] for i in range(0, len(b64), 76)], END])


def unseal(text: str, signer) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    start, end = text.find(BEGIN), text.find(END)
    if start < 0 or end < start:
        raise ValueError("no sealed report in the text")
    sealed = base64.b64decode("".join(text[start + len(BEGIN):end].split()))
    return AESGCM(_seal_key(signer)).decrypt(sealed[:12], sealed[12:], SEAL_INFO).decode("utf-8")


def red_team_issue(findings: List[Dict[str, str]], signer, day: Optional[str] = None) -> Dict[str, str]:
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    counts = {s: sum(1 for f in findings if f.get("severity") == s) for s in ("high", "medium", "low")}
    said = ", ".join(f"{n} {s}" for s, n in counts.items())
    return {
        "title": f"Monthly red-team, {day}: {said}",
        "body": (f"A model ({models.model()}) read the inspector's own code for ways a seller, a network or a "
                 f"mistake could make a sheet wrong or the run unsafe, and found {said}.\n\n"
                 "The findings are sealed to the inspector's signing key so that a public issue does not show an "
                 "unfixed weakness. To read them:\n\n```sh\ngh issue view <this issue's number> --json body -q .body"
                 " | agoranome-inspector reveal --key-file inspector-signing-key.pem\n```\n\n"
                 "Close this issue once each finding is fixed or judged not to apply.\n\n```text\n"
                 + seal(report_text(findings, day), signer) + "\n```\n"),
    }


# --- Opening an issue ---------------------------------------------------------------------------------------------

def open_issue(issue: Dict[str, str], *, repo: Optional[str] = None, token: Optional[str] = None,
               post: Optional[Callable[..., Any]] = None) -> Optional[str]:
    """Open the issue with the job's own GITHUB_TOKEN; its URL, or None."""
    repo = repo or os.environ.get("GITHUB_REPOSITORY")
    token = token or os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        print("no GITHUB_REPOSITORY or GITHUB_TOKEN: the issue is printed instead\n\n"
              + issue["title"] + "\n\n" + issue["body"])
        return None
    if post is None:
        import httpx

        post = httpx.post
    resp = post(f"https://api.github.com/repos/{repo}/issues", json=issue, timeout=30.0, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"})
    resp.raise_for_status()
    return resp.json().get("html_url")
