"""Central outbound URL and destination policy.

Caller-controlled browsing and fetch operations are public-internet tools by
default. Private-network access requires an explicit host allowlist or the
global private-network opt-in.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlsplit

from config import get_settings
from core.foundation import SurfException


class OutboundPolicyError(SurfException):
    """Raised when an outbound URL violates the configured egress policy."""

    def __init__(self, message: str):
        super().__init__(message, error_code="OUTBOUND_TARGET_BLOCKED")


@dataclass(frozen=True)
class ValidatedTarget:
    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]


class OutboundPolicy:
    """Validate schemes, credentials, DNS answers, and destination addresses."""

    def __init__(self) -> None:
        self._dns_cache: dict[tuple[str, int], tuple[float, tuple[str, ...]]] = {}
        self._dns_lock = asyncio.Lock()

    async def validate(
        self,
        url: str,
        *,
        allowed_schemes: Iterable[str] = ("http", "https"),
    ) -> ValidatedTarget:
        settings = get_settings()
        if not url or len(url) > settings.max_url_length:
            raise OutboundPolicyError("Outbound URL is empty or too long")

        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise OutboundPolicyError("Outbound URL has an invalid port") from exc

        scheme = parsed.scheme.lower()
        schemes = {value.lower() for value in allowed_schemes}
        if scheme not in schemes:
            raise OutboundPolicyError(f"Outbound URL scheme '{scheme or 'missing'}' is not allowed")
        if parsed.username is not None or parsed.password is not None:
            raise OutboundPolicyError("Outbound URLs may not contain embedded credentials")

        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            raise OutboundPolicyError("Outbound URL must include a hostname")
        if port is None:
            port = 443 if scheme in {"https", "wss"} else 80
        if port <= 0 or port > 65535:
            raise OutboundPolicyError("Outbound URL port is invalid")

        host_allowed = self._host_allowed(host, settings.outbound_allowed_hosts)
        addresses = await self._resolve(host, port)
        if not addresses:
            raise OutboundPolicyError("Outbound hostname did not resolve")

        if not settings.outbound_allow_private_networks and not host_allowed:
            blocked = [address for address in addresses if not self._is_public(address)]
            if blocked:
                raise OutboundPolicyError("Outbound target resolves to a non-public address")

        return ValidatedTarget(
            url=url,
            scheme=scheme,
            host=host,
            port=port,
            addresses=addresses,
        )

    async def _resolve(self, host: str, port: int) -> tuple[str, ...]:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None:
            return (str(address),)

        settings = get_settings()
        key = (host, port)
        now = time.monotonic()
        cached = self._dns_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

        async with self._dns_lock:
            cached = self._dns_cache.get(key)
            now = time.monotonic()
            if cached and cached[0] > now:
                return cached[1]
            try:
                infos = await asyncio.wait_for(
                    asyncio.get_running_loop().getaddrinfo(
                        host,
                        port,
                        family=socket.AF_UNSPEC,
                        type=socket.SOCK_STREAM,
                    ),
                    timeout=settings.outbound_dns_timeout_seconds,
                )
            except (asyncio.TimeoutError, OSError, socket.gaierror) as exc:
                raise OutboundPolicyError("Outbound hostname resolution failed") from exc

            addresses = tuple(dict.fromkeys(info[4][0] for info in infos))
            self._dns_cache[key] = (
                now + settings.outbound_dns_cache_ttl_seconds,
                addresses,
            )
            return addresses

    @staticmethod
    def _host_allowed(host: str, patterns: Iterable[str]) -> bool:
        for raw_pattern in patterns:
            pattern = str(raw_pattern).lower().rstrip(".")
            if not pattern:
                continue
            if pattern.startswith("*."):
                suffix = pattern[1:]
                if host.endswith(suffix) and host != suffix[1:]:
                    return True
            elif host == pattern:
                return True
        return False

    @staticmethod
    def _is_public(value: str) -> bool:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_global


_policy: Optional[OutboundPolicy] = None


def get_outbound_policy() -> OutboundPolicy:
    global _policy
    if _policy is None:
        _policy = OutboundPolicy()
    return _policy
