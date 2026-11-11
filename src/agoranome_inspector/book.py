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

"""The open book: one public log that only grows, each entry chained to the one before and signed.

A book is a JSON Lines file, one entry a line:

  {"seq": 0, "prev": "0x00..00", "time": "2026-11-16T06:00:00Z", "kind": "key", "body": {...},
   "hash": "0x...", "sig": {"kid": "...", "alg": "EdDSA", "value": "..."}}

  hash = sha256(canonical_json({seq, prev, time, kind, body}))
  sig  = Ed25519 over the 32 bytes of `hash`, by the key in force at that entry

The first entry is a `key` entry that names the signing key and is signed by it. A later `key` entry, signed
by the key in force, hands over to a new key. Nothing is ever edited or removed: a correction is a new entry.
Anyone who keeps an entry's seq and hash can later check that the book still holds it (see verify.py).

Kinds written by this package: key, sheet, changes, links, anchor, pledge, shelf, note. A verifier ignores kinds it does not know,
beyond checking their chain and signature.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from agoranome_inspector.canonical import ZERO_HASH, canonical, digest
from agoranome_inspector.keys import Signer, verify_signature

KINDS = ("key", "sheet", "changes", "links", "pick", "anchor", "pledge", "shelf", "reports", "note")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def core(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {k: entry[k] for k in ("seq", "prev", "time", "kind", "body")}


def entry_hash(entry: Dict[str, Any]) -> str:
    return digest(core(entry))


def parse(text: str) -> List[Dict[str, Any]]:
    entries = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError as e:
            raise ValueError(f"line {number} of the book is not JSON") from e
        if not isinstance(entry, dict):
            raise ValueError(f"line {number} of the book is not an object")
        entries.append(entry)
    return entries


@dataclass
class Check:
    """What a check of the book found: `ok` only when nothing failed."""
    entries: int = 0
    keys: List[Dict[str, str]] = field(default_factory=list)
    head: Optional[Dict[str, Any]] = None
    failures: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures and self.entries > 0


def check_chain(entries: List[Dict[str, Any]], pinned_kid: Optional[str] = None,
                since: Optional[Dict[str, Any]] = None) -> Check:
    """Check every entry's place, hash and signature, and the key hand-overs. `pinned_kid` is the first key's
    thumbprint as published elsewhere; `since` is an entry kept earlier ({"seq", "hash"}) that must still be
    in the book unchanged."""
    found = Check(entries=len(entries))
    # A kid is base64url, so it never holds spaces: a pasted one may carry a stray space or line end.
    pinned_kid = (pinned_kid or "").strip() or None
    if not entries:
        found.failures.append("the book is empty")
        return found
    key: Optional[Dict[str, str]] = None
    prev = ZERO_HASH
    for i, entry in enumerate(entries):
        where = f"entry {i}"
        try:
            if entry.get("seq") != i:
                found.failures.append(f"{where}: seq is {entry.get('seq')!r}, expected {i}")
                return found
            if entry.get("prev") != prev:
                found.failures.append(f"{where}: prev does not match the hash of entry {i - 1}")
                return found
            computed = entry_hash(entry)
        except (KeyError, TypeError) as e:
            found.failures.append(f"{where}: malformed ({e})")
            return found
        if entry.get("hash") != computed:
            found.failures.append(f"{where}: hash does not match its content")
            return found
        sig = entry.get("sig") or {}
        if i == 0:
            if entry.get("kind") != "key":
                found.failures.append("entry 0 is not a key entry")
                return found
            key = (entry.get("body") or {}).get("key")
            if not isinstance(key, dict):
                found.failures.append("entry 0 names no key")
                return found
            found.keys.append(key)
        if sig.get("kid") != (key or {}).get("kid") or sig.get("alg") != "EdDSA":
            found.failures.append(f"{where}: signed by {sig.get('kid')!r}, not by the key in force")
            return found
        if not verify_signature(key, bytes.fromhex(computed[2:]), str(sig.get("value", ""))):
            found.failures.append(f"{where}: signature does not verify")
            return found
        if i > 0 and entry.get("kind") == "key":
            new_key = (entry.get("body") or {}).get("key")
            if not isinstance(new_key, dict):
                found.failures.append(f"{where}: key entry names no key")
                return found
            key = new_key
            found.keys.append(key)
        prev = computed
    if pinned_kid and found.keys and found.keys[0].get("kid") != pinned_kid:
        found.failures.append(f"the book's first key is {found.keys[0].get('kid')}, not the pinned {pinned_kid}")
    if since is not None:
        seq = since.get("seq")
        if not isinstance(seq, int) or seq < 0 or seq >= len(entries):
            found.failures.append(f"the kept entry {seq!r} is no longer in the book")
        elif entries[seq]["hash"] != since.get("hash"):
            found.failures.append(f"entry {seq} has changed since it was kept")
    last = entries[-1]
    found.head = {"seq": last["seq"], "hash": last["hash"], "time": last["time"]}
    return found


class Book:
    """A book on disk, written by one signer at a time."""

    def __init__(self, path: str):
        self.path = Path(path)

    def entries(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        return parse(self.path.read_text(encoding="utf-8"))

    def find(self, kind: str, **match: Any) -> List[Dict[str, Any]]:
        return [e for e in self.entries()
                if e.get("kind") == kind and all((e.get("body") or {}).get(k) == v for k, v in match.items())]

    def _write(self, entry: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(canonical(entry).decode("utf-8") + "\n")

    def append(self, signer: Signer, kind: str, body: Dict[str, Any], time: Optional[str] = None) -> Dict[str, Any]:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        existing = self.entries()
        if not existing and kind != "key":
            existing = [self.open(signer, time=time)]
        if existing:
            checked = check_chain(existing)
            if not checked.ok:
                raise RuntimeError("the book on disk does not verify: " + "; ".join(checked.failures))
            if checked.keys[-1].get("kid") != signer.kid:
                raise RuntimeError(f"the key in force is {checked.keys[-1].get('kid')}, not {signer.kid}")
        seq = len(existing)
        prev = existing[-1]["hash"] if existing else ZERO_HASH
        entry = {"seq": seq, "prev": prev, "time": time or utc_now(), "kind": kind, "body": body}
        entry["hash"] = entry_hash(entry)
        entry["sig"] = {"kid": signer.kid, "alg": "EdDSA", "value": signer.sign(bytes.fromhex(entry["hash"][2:]))}
        self._write(entry)
        return entry

    def open(self, signer: Signer, time: Optional[str] = None, note: Optional[str] = None) -> Dict[str, Any]:
        """Write the first entry: the key that signs the book."""
        if self.entries():
            raise RuntimeError("the book is already open")
        body = {"key": signer.jwk, "note": note or "The key that signs this book."}
        entry = {"seq": 0, "prev": ZERO_HASH, "time": time or utc_now(), "kind": "key", "body": body}
        entry["hash"] = entry_hash(entry)
        entry["sig"] = {"kid": signer.kid, "alg": "EdDSA", "value": signer.sign(bytes.fromhex(entry["hash"][2:]))}
        self._write(entry)
        return entry

    def hand_over(self, current: Signer, new: Signer, time: Optional[str] = None) -> Dict[str, Any]:
        """A key entry signed by the key in force that names the next key."""
        return self.append(current, "key", {"key": new.jwk, "note": "The key that signs this book from here."},
                           time=time)


def entries_of(kind: str, entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [e for e in entries if e.get("kind") == kind]
