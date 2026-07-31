"""Shared test configuration."""
import pytest


@pytest.fixture
def allow_private_networks(monkeypatch):
    """Allow tests to reach local fixture servers."""
    from config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "outbound_allow_private_networks", True)
    # Wipe any DNS cache entries that may have been resolved before patching.
    from services.outbound_policy import get_outbound_policy

    policy = get_outbound_policy()
    policy._dns_cache.clear()
