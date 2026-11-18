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

"""Who a seller is, for pick-2's two places a seller (pick.py).

A host is not a seller: one operator can list on many hosts, and a subdomain costs nothing. Two hosts are one seller
when they

  share a pay-to address that few hosts list (at most PLATFORM_HOSTS, 5): money paid to either goes to the same
  wallet; or
  share a registrable domain (api.example.com and staging.example.com), unless the domain is a shared platform's
  (x.workers.dev, y.onrender.com) or an open name service's (1-2-3-4.sslip.io).

A pay-to that more hosts list is a platform's or a processor's, and links only hosts that also share a registrable
domain. A seller is a connected component of those links, named by its first host, A to Z. Nothing here reads a file
or makes a request. This is the Agoranome Lab's seller rule (src/revenue/insights/sellers.py and the registrable
domain of src/revenue/seller/safety.py), copied so the pick can be recomputed from the signed tables alone.
"""

import ipaddress
import re
from typing import Callable, Dict, Iterable, List, Optional, TypeVar

T = TypeVar("T")

PLATFORM_HOSTS = 5
_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$")

# A host under one of these is a platform's subdomain: the platform's domain says nothing about the seller.
SHARED_DOMAINS = (
    "ngrok.io", "ngrok.app", "ngrok-free.app", "trycloudflare.com", "loca.lt", "localtunnel.me", "serveo.net",
    "pinggy.link", "lhr.life", "vercel.app", "netlify.app", "workers.dev", "pages.dev", "onrender.com",
    "herokuapp.com", "fly.dev", "railway.app", "github.io", "replit.app", "replit.dev", "repl.co", "glitch.me",
    "azurewebsites.net", "cloudfunctions.net", "run.app", "appspot.com", "web.app", "firebaseapp.com",
    "amazonaws.com", "deno.dev", "supabase.co", "modal.run", "hf.space", "lovable.app", "up.railway.app",
    "koyeb.app", "val.run", "web.val.run", "netlify.com", "render.com", "bolt.new", "zeabur.app",
)
# Two-label public suffixes common enough among sellers that the registrable domain is the last three labels.
TWO_LABEL_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "ltd.uk", "plc.uk", "com.au", "net.au", "org.au", "edu.au",
    "co.nz", "org.nz", "co.jp", "ne.jp", "or.jp", "com.br", "net.br", "org.br", "com.cn", "net.cn", "org.cn",
    "com.hk", "com.sg", "com.tw", "co.kr", "co.in", "net.in", "org.in", "co.za", "com.mx", "com.tr", "com.ar",
    "co.id", "com.my", "com.ph", "com.vn", "co.il", "com.ua", "com.pl", "co.th",
}
# Names anyone can take a subdomain of without registering anything, beyond SHARED_DOMAINS. Hosting providers'
# default names (srv123.hstgr.cloud, x.ondigitalocean.app) are a shared platform's too.
OPEN_NAME_DOMAINS = ("sslip.io", "nip.io", "xip.io", "ts.net", "duckdns.org", "localhost.run", "ngrok.dev",
                     "ngrok-free.dev", "github.dev", "trycloudflare.com", "hstgr.cloud", "cloudfront.net",
                     "ondigitalocean.app", "azurecontainerapps.io", "gitbook.io", "vusercontent.net", "bolt.host",
                     "base44.app", "manus.space", "convex.site", "convex.cloud", "edgeone.app", "dynv6.net",
                     "no-ip.org", "ddns.net", "cloudns.ph", "vps.ovh.net", "contaboserver.net", "linodeusercontent.com")


def registrable(host: str) -> Optional[str]:
    """The domain a host's owner registered (its last two labels, three under a two-label suffix), or None for a
    host on a shared platform's domain or one that isn't a public domain name."""
    host = (host or "").strip().lower().rstrip(".")
    if not _HOST.match(host):
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    if any(host == d or host.endswith("." + d) for d in SHARED_DOMAINS):
        return None
    labels = host.split(".")
    if len(labels) >= 3 and ".".join(labels[-2:]) in TWO_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def domain_of(host: str) -> Optional[str]:
    """The registrable domain of a host, or None for one on a shared platform, an open name service or an address."""
    host = (host or "").strip().lower().rstrip(".")
    if not host or any(host == d or host.endswith("." + d) for d in OPEN_NAME_DOMAINS):
        return None
    return registrable(host.split(":")[0])


class _Union:
    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def join(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            first, second = sorted((ra, rb))
            self.parent[second] = first


def seller_of(items: Iterable[T], host: Callable[[T], str], pay_to: Callable[[T], str]) -> Dict[str, str]:
    """Each host's seller: the first host, A to Z, of the hosts linked to it through the items (listings)."""
    items = list(items)
    hosts = sorted({(host(i) or "").strip().lower() for i in items} - {""})
    union = _Union()
    for h in hosts:
        union.find(h)
    by_pay_to: Dict[str, set] = {}
    for i in items:
        h, address = (host(i) or "").strip().lower(), (pay_to(i) or "").strip().lower()
        if h and address:
            by_pay_to.setdefault(address, set()).add(h)
    for sharing in by_pay_to.values():
        group = sorted(sharing)
        if len(group) <= PLATFORM_HOSTS:
            for other in group[1:]:
                union.join(group[0], other)
        else:   # a platform's pay-to: only hosts that also share a domain
            by_domain: Dict[str, List[str]] = {}
            for h in group:
                d = domain_of(h)
                if d:
                    by_domain.setdefault(d, []).append(h)
            for same in by_domain.values():
                for other in same[1:]:
                    union.join(same[0], other)
    by_domain_all: Dict[str, List[str]] = {}
    for h in hosts:
        d = domain_of(h)
        if d:
            by_domain_all.setdefault(d, []).append(h)
    for same in by_domain_all.values():
        for other in same[1:]:
            union.join(same[0], other)
    return {h: union.find(h) for h in hosts}
