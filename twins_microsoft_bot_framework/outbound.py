"""Outbound URL policy for metadata fetches in cloud deployments.

Cloud deployments fetch OpenID metadata, JWKS documents and token
endpoints only over https, only from hosts that resolve to public
addresses, and without following redirects. Local deployments are not
restricted: pointing the bot half at a channel on localhost is the
documented workflow.
"""

import ipaddress
import socket
from urllib.parse import urlparse


class OutboundURLRejected(ValueError):
    """The URL is not an allowed outbound target."""


def _is_public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_outbound_url(url: str) -> None:
    """Raise :class:`OutboundURLRejected` unless ``url`` is an https URL
    whose host resolves only to public addresses."""
    try:
        parsed = urlparse(url)
        port = parsed.port or 443
    except ValueError as exc:
        raise OutboundURLRejected("malformed url") from exc
    if parsed.scheme != "https":
        raise OutboundURLRejected("scheme must be https")
    host = parsed.hostname
    if not host:
        raise OutboundURLRejected("missing host")
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise OutboundURLRejected("host does not resolve") from exc
    if not infos:
        raise OutboundURLRejected("host does not resolve")
    for info in infos:
        if not _is_public(info[4][0]):
            raise OutboundURLRejected("host resolves to a non-public address")
