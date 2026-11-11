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

"""Networks, assets and addresses as x402 names them, made comparable.

x402 v1 names a network by a short name ("base"), v2 by its CAIP-2 id ("eip155:8453"). An EVM address is
compared in lower case; a Solana address is case-sensitive base58 and is kept as it is.
"""

import re
from decimal import Decimal
from typing import Any, Optional

WHOLE = re.compile(r"^[0-9]{1,78}$")   # at most a uint256

# x402 v1 short names, as the reference SDKs list them, and their CAIP-2 ids.
LEGACY = {
    "base": "eip155:8453",
    "base-sepolia": "eip155:84532",
    "ethereum": "eip155:1",
    "sepolia": "eip155:11155111",
    "polygon": "eip155:137",
    "polygon-amoy": "eip155:80002",
    "arbitrum": "eip155:42161",
    "optimism": "eip155:10",
    "avalanche": "eip155:43114",
    "avalanche-fuji": "eip155:43113",
    "solana": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
    "solana-devnet": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
}
TESTNETS = {
    "eip155:84532", "eip155:11155111", "eip155:80002", "eip155:43113",
    "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
}
NAMES = {
    "eip155:8453": "Base", "eip155:84532": "Base Sepolia", "eip155:1": "Ethereum",
    "eip155:137": "Polygon", "eip155:42161": "Arbitrum", "eip155:10": "Optimism",
    "eip155:43114": "Avalanche", "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp": "Solana",
}

# USDC on the networks x402 sellers use (6 decimals), keyed by (network, asset as compared).
USDC = {
    ("eip155:8453", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"),
    ("eip155:84532", "0x036cbd53842c5426634e7929541ec2318f3dcf7e"),
    ("eip155:1", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"),
    ("eip155:137", "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"),
    ("eip155:42161", "0xaf88d065e77c8cc2239327c5edb3a432268e5831"),
    ("eip155:10", "0x0b2c639c533813f4aa9d7837caf62653d097ff85"),
    ("eip155:43114", "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e"),
    ("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"),
}
USDC_DECIMALS = 6


CAIP2_REFERENCE_MAX = 32


def network(value: Any) -> Optional[str]:
    """A network as a CAIP-2 id where the name is known, else as given (stripped).

    A CAIP-2 reference is at most 32 characters. Chains named by their genesis hash (Solana, Algorand) are
    sometimes written with the whole hash, "algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73ktiC1qzkkit8=", and
    sometimes as CAIP-2 says, "algorand:wGHE2Pwdvd7S12BL5FaOP20EGYesN73k": both name one network, so the
    reference is cut to 32 characters."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower() in LEGACY:
        return LEGACY[text.lower()]
    namespace, sep, reference = text.partition(":")
    if sep and namespace and len(reference) > CAIP2_REFERENCE_MAX:
        return f"{namespace}:{reference[:CAIP2_REFERENCE_MAX]}"
    return text


def address(value: Any) -> Optional[str]:
    """An address as compared: EVM hex in lower case, anything else as given."""
    text = str(value or "").strip()
    if not text:
        return None
    return text.lower() if text.lower().startswith("0x") else text


def amount(value: Any) -> Optional[str]:
    """An atomic amount as a decimal string of a non-negative integer, or None when it is not one."""
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    if not WHOLE.match(text):
        return None
    return str(int(text))


def is_usdc(net: Optional[str], asset: Optional[str]) -> bool:
    return (net, asset) in USDC


def usd(net: Optional[str], asset: Optional[str], atomic: Optional[str]) -> Optional[str]:
    """The USD value of a USDC amount as an exact decimal string, None for any other asset."""
    if atomic is None or not is_usdc(net, asset):
        return None
    value = Decimal(int(atomic)).scaleb(-USDC_DECIMALS)
    return format(value.normalize(), "f") if value else "0"


def is_testnet(net: Optional[str]) -> bool:
    return net in TESTNETS


# --- Strict formats -----------------------------------------------------------------------------------------------
# Every field a seller writes and the sheet keeps must look like what it is, so that no seller can put a sentence
# (an instruction aimed at buyer agents, say) into a signed sheet. A field that does not is dropped, and an option
# without a usable network, asset, amount and pay-to is not payable.

CAIP2 = re.compile(r"^[-a-z0-9]{3,8}:[-_a-zA-Z0-9]{1,32}$")
V1_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
SCHEME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
HEX_ADDRESS = re.compile(r"^0x[0-9a-f]{40,64}$")
EVM_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
TOKEN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
VERSION = re.compile(r"^[0-9]{1,3}(\.[0-9]{1,3}){0,2}$")


def strict_network(value: Any) -> Optional[str]:
    """A network as a CAIP-2 id, or an x402 v1 short name not mapped yet; None for anything else."""
    found = network(value)
    return found if found and (CAIP2.match(found) or V1_NAME.match(found)) else None


def strict_scheme(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text if SCHEME.match(text) else None


def identifier(value: Any) -> Optional[str]:
    """An address or asset id: hex after 0x (in lower case), else letters, digits and . _ : - only, at most 80."""
    found = address(value)
    if found is None:
        return None
    if found.startswith("0x"):
        return found if HEX_ADDRESS.match(found) else None
    return found if TOKEN_ID.match(found) else None


def pay_to(value: Any, net: Optional[str]) -> Optional[str]:
    """A pay-to address; on an EVM network it must be a 20-byte address."""
    found = identifier(value)
    if found and net and net.startswith("eip155:") and not EVM_ADDRESS.match(found):
        return None
    return found


def version(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text if VERSION.match(text) else None


URL = re.compile(r"^https?://[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?(/[^\s\"'<>\\^`{|}]*)?$")


def is_url(value: Any) -> bool:
    """An http(s) URL with a host name and no spaces, quotes or angle brackets, at most 2048 characters."""
    return isinstance(value, str) and len(value) <= 2048 and bool(URL.match(value))
