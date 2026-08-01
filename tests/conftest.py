"""Shared test configuration."""
import pytest


@pytest.fixture
def deny_private_networks(monkeypatch):
    """Pin the egress guard closed.

    Security assertions must hold regardless of the operator's .env, which may
    enable SURF_OUTBOUND_ALLOW_PRIVATE_NETWORKS for local UI testing.
    """
    from config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "outbound_allow_private_networks", False)
    from services.outbound_policy import get_outbound_policy

    get_outbound_policy()._dns_cache.clear()


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
