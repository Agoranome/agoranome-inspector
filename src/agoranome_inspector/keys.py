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

"""The book's signing key: Ed25519, named by its RFC 7638 JWK thumbprint.

The private key is read from a PEM file or from the INSPECTOR_SIGNING_KEY environment variable (PEM text, or
the 32-byte seed in base64url). It is never written into the book or the published files.
"""

import hashlib
import os
from pathlib import Path
from typing import Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from agoranome_inspector.canonical import b64url, b64url_decode, canonical

ENV_KEY = "INSPECTOR_SIGNING_KEY"


def thumbprint(jwk: Dict[str, str]) -> str:
    """RFC 7638 thumbprint of an OKP key: SHA-256 over its required members, base64url."""
    required = {k: jwk[k] for k in ("crv", "kty", "x")}
    return b64url(hashlib.sha256(canonical(required)).digest())


def public_jwk(public: Ed25519PublicKey) -> Dict[str, str]:
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": b64url(raw)}
    return {**jwk, "kid": thumbprint(jwk), "alg": "EdDSA", "use": "sig"}


def jwk_public_key(jwk: Dict[str, str]) -> Ed25519PublicKey:
    if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
        raise ValueError("only Ed25519 keys are accepted")
    raw = b64url_decode(jwk["x"])
    if len(raw) != 32:
        raise ValueError("an Ed25519 public key is 32 bytes")
    if jwk.get("kid") and jwk["kid"] != thumbprint(jwk):
        raise ValueError("the key's kid is not its thumbprint")
    return Ed25519PublicKey.from_public_bytes(raw)


class Signer:
    def __init__(self, private: Ed25519PrivateKey):
        self.private = private
        self.jwk = public_jwk(private.public_key())
        self.kid = self.jwk["kid"]

    @classmethod
    def generate(cls) -> "Signer":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_text(cls, text: str) -> "Signer":
        text = text.strip()
        if text.startswith("-----BEGIN"):
            key = serialization.load_pem_private_key(text.encode(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("the PEM key is not an Ed25519 key")
            return cls(key)
        seed = b64url_decode(text)
        if len(seed) != 32:
            raise ValueError("a base64url Ed25519 seed must be 32 bytes")
        return cls(Ed25519PrivateKey.from_private_bytes(seed))

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Signer":
        """From `path`, else from the INSPECTOR_SIGNING_KEY environment variable."""
        if path:
            return cls.from_text(Path(path).read_text())
        text = os.environ.get(ENV_KEY)
        if not text:
            raise LookupError(f"no signing key: pass --key-file or set {ENV_KEY}")
        return cls.from_text(text)

    def pem(self) -> str:
        return self.private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()).decode()

    def sign(self, message: bytes) -> str:
        return b64url(self.private.sign(message))


def verify_signature(jwk: Dict[str, str], message: bytes, signature: str) -> bool:
    try:
        jwk_public_key(jwk).verify(b64url_decode(signature), message)
        return True
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return False
