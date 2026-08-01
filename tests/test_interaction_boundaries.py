from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from controllers.browser_controller import interact_with_element
from controllers.session_controller import create_session
from models.schemas import InteractRequest, SessionConfig, SessionCreateRequest
from pydantic import ValidationError


class SessionOperations:
    @asynccontextmanager
    async def session_operation(self, session_id, operation):
        yield object()

    update_session_stats = AsyncMock()


@pytest.mark.asyncio
async def test_legacy_interaction_error_boundary_is_unchanged():
    browser = AsyncMock()
    browser.interact_with_element.side_effect = RuntimeError("diagnostic must stay hidden")
    request = InteractRequest(
        session_id="sess_12345678", action="click", selector=".two-matches"
    )

    with pytest.raises(HTTPException) as exc_info:
        await interact_with_element(
            request=request,
            browser_service=browser,
            session_service=SessionOperations(),
            user={},
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Element interaction failed"


@pytest.mark.asyncio
async def test_top_level_ephemeral_session_fields_reach_session_config():
    service = AsyncMock()
    service.create_session.return_value = SimpleNamespace(
        session_id="sess_12345678",
        config=SessionConfig(profile_id="throwaway", persist_profile=False),
        context=SimpleNamespace(expires_at=None),
    )

    await create_session(
        request=SessionCreateRequest(profile_id="throwaway", persist_profile=False),
        session_service=service,
        user={},
    )

    assert service.create_session.await_args.kwargs["user_config"] == {
        "profile_id": "throwaway",
        "persist_profile": False,
    }


def test_force_string_is_rejected_in_interaction_options():
    with pytest.raises(ValidationError):
        InteractRequest(
            session_id="sess_12345678",
            action="click",
            selector="#hidden",
            options={"force": "false"},
        )
