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

"""Canonical JSON and hashes: the bytes every hash and signature in the open book is taken over.

Canonical JSON here is keys sorted, no whitespace, UTF-8, and no floating-point numbers. Every amount is an
integer or a decimal string (x402 itself sends amounts as strings), so the bytes match RFC 8785 for the
ASCII keys this package writes, and any language can reproduce them.
"""

import base64
import hashlib
import json
from typing import Any

ZERO_HASH = "0x" + "00" * 32


def _reject_floats(value: Any, path: str = "$") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return
    if isinstance(value, float):
        raise TypeError(f"floating-point number at {path}: use an integer or a decimal string")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"non-string key at {path}")
            _reject_floats(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _reject_floats(item, f"{path}[{i}]")
        return
    raise TypeError(f"unsupported type {type(value).__name__} at {path}")


def canonical(value: Any) -> bytes:
    """The canonical bytes of a JSON value."""
    _reject_floats(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return "0x" + hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    """SHA-256 of a value's canonical bytes, as 0x-hex."""
    return sha256_hex(canonical(value))


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
