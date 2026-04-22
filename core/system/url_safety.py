"""URL safety — SSRF defence for adapters that fetch arbitrary
caller-supplied URLs.

Why this exists: the launch pipeline accepts caller-supplied
image URLs (gallery_urls) from `POST /api/launch`. Without
this module, `vision._download` and similar helpers would
happily follow the URL into internal network space (cloud
metadata 169.254.169.254, loopback 127.0.0.0/8, RFC 1918
private ranges, etc.), turning the HTTP endpoint into an
SSRF primitive.

Usage:

    from core.system.url_safety import is_safe_public_url
    if not is_safe_public_url(url):
        raise SecurityError(...)

Pure stdlib. No third-party DNS library — we rely on
``socket.getaddrinfo`` which resolves through the normal
DNS path and returns every A/AAAA the host owns (DNS
rebinding can't undo this without a second lookup; see
NOTES below).

NOTES on DNS rebinding: a fully robust fix would either
(a) pin the resolved IP across the connect, or (b) use
a vetted HTTP client that accepts pre-resolved IPs. Since
this codebase uses stdlib urllib, we accept the small
window where a TOCTOU rebind could race between the
safety check and the actual connect. For our threat
model (attacker → unauthenticated API → outbound HTTP),
this still blocks the 99% of exploit paths — naive
``http://169.254.169.254`` / localhost / RFC1918. Pinning
can be added later with a custom HTTPSHandler.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.parse

from utils.logger import get_logger


logger = get_logger("core.system.url_safety")


_SAFE_SCHEMES = frozenset({"https"})


def is_safe_public_url(url: str) -> bool:
    """Return True iff *url* is https to a host that resolves
    entirely to public (non-private, non-loopback,
    non-link-local, non-reserved) IPv4 / IPv6 addresses.

    Returns False for:
      * non-https schemes (http, ftp, file, gopher, …)
      * unresolvable hosts
      * hosts that resolve to any private / loopback /
        link-local / reserved IP (even one — mixed public
        + private is still rejected to close DNS rebinding
        partial-match exploits)
      * empty / malformed URLs
    """
    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in _SAFE_SCHEMES:
        return False
    host = (parsed.hostname or "").strip()
    if not host:
        return False
    # Literal IP in the URL? classify directly.
    try:
        ip = ipaddress.ip_address(host)
        return _ip_is_public(ip)
    except ValueError:
        pass
    # Hostname — resolve and check every returned address.
    try:
        infos = socket.getaddrinfo(
            host, None, type=socket.SOCK_STREAM,
        )
    except (socket.gaierror, OSError) as exc:
        logger.debug("url safety resolve failed %s: %s", host, exc)
        return False
    if not infos:
        return False
    for _, _, _, _, sockaddr in infos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except (ValueError, IndexError):
            return False
        if not _ip_is_public(ip):
            return False
    return True


def _ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    """True iff the address is routable on the public
    internet + not a special-use / metadata address."""
    if ip.is_loopback:
        return False
    if ip.is_link_local:
        return False
    if ip.is_private:
        return False
    if ip.is_reserved:
        return False
    if ip.is_multicast:
        return False
    if ip.is_unspecified:
        return False
    # IPv4 cloud metadata. ipaddress.is_link_local catches
    # 169.254.0.0/16 already, but pin for clarity.
    if isinstance(ip, ipaddress.IPv4Address):
        if str(ip) == "169.254.169.254":
            return False
    return True
