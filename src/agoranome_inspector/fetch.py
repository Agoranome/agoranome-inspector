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

"""Ask a stranger's endpoint for its offer without exposing the network the inspector runs on.

Lifted from the lab (AEAx src/revenue/seller/fetch.py). Only public https URLs are asked. The host is resolved
once, every address must be public, and the request is pinned to that address (SNI and the certificate check
still use the hostname), so DNS rebinding cannot swap the target after the check. No payment is sent, no
redirect is followed, proxy settings are ignored and at most `max_bytes` of the answer are read.
"""

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx

BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".corp")
USER_AGENT = "Agoranome-inspector/0.1 (+https://github.com/shariar-k/agoranome1; unpaid offer check, sends no payment)"


class FetchError(Exception):
    """A URL that could not be asked. `kind` is refused (not a URL we ask) or unreachable."""

    def __init__(self, message: str, kind: str = "unreachable"):
        super().__init__(message)
        self.kind = kind


@dataclass
class Fetched:
    url: str
    method: str
    status: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    truncated: bool = False
    www_authenticate: List[str] = field(default_factory=list)   # each header as sent, not joined


def resolve(host: str, port: int) -> List[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


def is_public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class SafeFetcher:
    def __init__(self, *, resolver: Callable[[str, int], List[str]] = resolve,
                 transport: Optional[httpx.BaseTransport] = None, timeout: float = 8.0, max_bytes: int = 65536,
                 user_agent: str = USER_AGENT):
        self.resolver = resolver
        self.transport = transport
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.user_agent = user_agent

    def target(self, url: str) -> Tuple[SplitResult, str, int, str]:
        """Validate a URL and pick the public address to connect to."""
        if len(url) > 2048:
            raise FetchError("the URL is longer than 2048 characters", "refused")
        parts = urlsplit(url.strip())
        if parts.scheme != "https":
            raise FetchError("only https URLs are asked", "refused")
        if parts.username or parts.password:
            raise FetchError("URLs with credentials are not asked", "refused")
        host = (parts.hostname or "").rstrip(".").lower()
        try:
            ipaddress.ip_address(host)
            raise FetchError("an IP address in place of a hostname is not asked", "refused")
        except ValueError:
            pass
        if "." not in host or host == "localhost" or host.endswith(BLOCKED_SUFFIXES):
            raise FetchError("the host is not a public domain name", "refused")
        try:
            port = parts.port or 443
        except ValueError as e:
            raise FetchError("the URL has an invalid port", "refused") from e
        try:
            addresses = self.resolver(host, port)
        except UnicodeError as e:
            raise FetchError("the host is not a valid domain name", "refused") from e
        except OSError as e:
            raise FetchError(f"could not resolve {host}") from e
        if not addresses:
            raise FetchError(f"could not resolve {host}")
        if not all(is_public(a) for a in addresses):
            raise FetchError(f"{host} resolves to a non-public address", "refused")
        return parts, host, port, addresses[0]

    def fetch(self, url: str, method: str = "GET", json_body: Optional[dict] = None) -> Fetched:
        """One request, pinned to the checked address. The whole answer must arrive within twice the timeout, so a
        host that sends one byte at a time cannot hold a worker."""
        parts, host, port, addr = self.target(url)
        ip_host = f"[{addr}]" if ":" in addr else addr
        netloc = ip_host if port == 443 else f"{ip_host}:{port}"
        pinned = urlunsplit(("https", netloc, parts.path or "/", parts.query, ""))
        headers = {"User-Agent": self.user_agent, "Accept": "application/json",
                   "Host": host if port == 443 else f"{host}:{port}"}
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout, follow_redirects=False,
                              trust_env=False) as client:
                with client.stream(method, pinned, headers=headers, json=json_body,
                                   extensions={"sni_hostname": host}) as resp:
                    body = bytearray()
                    truncated = False
                    give_up = time.monotonic() + 2 * self.timeout
                    for chunk in resp.iter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_bytes or time.monotonic() > give_up:
                            truncated = True
                            break
                    return Fetched(url=url, method=method, status=resp.status_code,
                                   headers={k.lower(): v for k, v in resp.headers.items()},
                                   body=bytes(body[: self.max_bytes]), truncated=truncated,
                                   www_authenticate=[v[:8192] for v in resp.headers.get_list("www-authenticate")][:32])
        except httpx.HTTPError as e:
            raise FetchError(f"could not reach {host} ({type(e).__name__})") from e
        except (httpx.InvalidURL, UnicodeError) as e:
            raise FetchError("the URL could not be sent", "refused") from e
