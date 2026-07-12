"""Text cleaning utilities ported from SENTRY ETL patterns."""

from __future__ import annotations

import html
import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s+")
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_UNICODE_DASH_RE = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2015]")


def clean_text(text: str) -> str:
    """Strip HTML, decode entities, normalize Unicode, collapse whitespace."""
    if not text:
        return ""
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text)
    text = _UNICODE_DASH_RE.sub("-", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()
