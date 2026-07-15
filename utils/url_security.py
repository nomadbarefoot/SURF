"""URL handling helpers for security-sensitive diagnostics."""
from __future__ import annotations

from urllib.parse import urlsplit


def safe_url_for_log(value: object) -> str:
    """Return an origin only, excluding credentials, paths, queries, and fragments."""
    try:
        parsed = urlsplit(str(value))
        if not parsed.scheme or not parsed.hostname:
            return "<invalid-url>"
        default_port = 443 if parsed.scheme.lower() in {"https", "wss"} else 80
        authority = parsed.hostname.lower().rstrip(".")
        if parsed.port and parsed.port != default_port:
            authority = f"{authority}:{parsed.port}"
        return f"{parsed.scheme.lower()}://{authority}"
    except (TypeError, ValueError):
        return "<invalid-url>"
