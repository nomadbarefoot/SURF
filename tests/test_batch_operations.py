"""Batch-operation schema and enum conversion regressions."""
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from controllers.browser_controller import _execute_operation
from models.schemas import BatchRequest, ExtractType, InteractionAction


def test_batch_request_caps_operation_count():
    with pytest.raises(ValidationError):
        BatchRequest(
            session_id="sess_12345678",
            operations=[{"type": "extract"}] * 11,
        )


@pytest.mark.asyncio
async def test_batch_extract_converts_string_to_enum():
    browser = AsyncMock()
    browser.extract_content.return_value = {"content": "ok"}

    result = await _execute_operation(
        {"type": "extract", "extract_type": "text"}, object(), browser
    )

    assert result["success"] is True
    assert browser.extract_content.await_args.kwargs["extract_type"] is ExtractType.TEXT


@pytest.mark.asyncio
async def test_batch_interaction_converts_string_to_enum():
    browser = AsyncMock()
    browser.interact_with_element.return_value = {"clicked": True}

    result = await _execute_operation(
        {"type": "interact", "action": "click", "selector": "#submit"},
        object(),
        browser,
    )

    assert result["success"] is True
    assert (
        browser.interact_with_element.await_args.kwargs["action"]
        is InteractionAction.CLICK
    )
