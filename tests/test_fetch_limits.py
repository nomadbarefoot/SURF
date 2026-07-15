"""Response-body budget tests for all fetch backends."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.foundation import ResourceLimitError
from services.fetch_service import FetchService


def test_incremental_response_limit_rejects_oversized_chunk():
    service = FetchService()
    content = bytearray(b"1234")

    with patch("config.get_settings") as mocked_settings:
        mocked_settings.return_value.max_response_size = 5
        with pytest.raises(ResourceLimitError):
            service._extend_limited(content, b"56")

    assert content == b"1234"


def test_large_json_is_not_parsed_after_body_is_bounded():
    service = FetchService()
    body = b'{"payload":"' + (b"x" * 100) + b'"}'

    with patch("config.get_settings") as mocked_settings:
        mocked_settings.return_value.max_response_size = 1024
        mocked_settings.return_value.max_json_parse_size = 32
        result = service._format_response(200, "https://example.com", {}, body)

    assert result["length"] == len(body)
    assert result["json"] is None
