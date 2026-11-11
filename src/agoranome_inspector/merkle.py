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

"""The Merkle tree, the same construction as the lab's pledge ledger (AEAx src/revenue/machine/impact.py).

One construction proves both a row of the sheet and a receipt of the lab's ledger:

  leaf = sha256(0x00 || canonical_json(value))
  node = sha256(0x01 || min(a, b) || max(a, b))    (sorted pairs, no positions)
  Leaves are sorted; an odd node is promoted unchanged to the next level.

The lab hashes a receipt's four public fields {receipt_id, payer, amount_atomic, tx_hash}; the sheet hashes a
whole row.
"""

import hashlib
from typing import Any, Dict, List, Optional

from agoranome_inspector.canonical import canonical


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def leaf_hash(value: Any) -> str:
    """The leaf of one JSON value (0x-hex)."""
    return "0x" + _h(b"\x00" + canonical(value)).hex()


def receipt_leaf(entry: Dict[str, Any]) -> str:
    """The lab ledger's leaf for one settled receipt: only its four public fields are hashed."""
    return leaf_hash({k: entry[k] for k in ("receipt_id", "payer", "amount_atomic", "tx_hash")})


def _node(a: bytes, b: bytes) -> bytes:
    lo, hi = sorted((a, b))
    return _h(b"\x01" + lo + hi)


def _levels(leaves: List[str]) -> List[List[bytes]]:
    level = sorted(bytes.fromhex(x[2:]) for x in leaves)
    levels = [level]
    while len(level) > 1:
        nxt = [_node(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])
        levels.append(nxt)
        level = nxt
    return levels


def merkle_root(leaves: List[str]) -> Optional[str]:
    if not leaves:
        return None
    return "0x" + _levels(leaves)[-1][0].hex()


def merkle_proof(leaves: List[str], leaf: str) -> List[str]:
    """Sibling hashes from `leaf` up to the root (empty for a one-leaf tree)."""
    levels = _levels(leaves)
    index = levels[0].index(bytes.fromhex(leaf[2:]))
    proof = []
    for level in levels[:-1]:
        sibling = index ^ 1
        if sibling < len(level):
            proof.append("0x" + level[sibling].hex())
        index //= 2
    return proof


def verify_proof(leaf: str, proof: List[str], root: str) -> bool:
    try:
        node = bytes.fromhex(leaf[2:])
        for sibling in proof:
            node = _node(node, bytes.fromhex(sibling[2:]))
    except (ValueError, TypeError):
        return False
    return "0x" + node.hex() == (root or "").lower()
