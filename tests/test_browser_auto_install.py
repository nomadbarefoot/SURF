"""Chromium auto-install on first launch."""

import pytest

from core.foundation import ConfigurationError
from services import session_service as ss


class _Launcher:
    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "context"


def _service():
    return ss.SessionService.__new__(ss.SessionService)


MISSING = Exception("Executable doesn't exist at /ms-playwright/chromium/chrome")


@pytest.mark.asyncio
async def test_missing_browser_installs_once_then_retries(monkeypatch):
    installs = []

    async def fake_install(browser_type):
        installs.append(browser_type)

    monkeypatch.setattr(ss, "install_playwright_browser", fake_install)
    monkeypatch.setattr(ss.settings, "browser_auto_install", True)
    launch = _Launcher([MISSING])
    assert await _service()._launch_with_install("chromium", launch) == "context"
    assert installs == ["chromium"] and launch.calls == 2


@pytest.mark.asyncio
async def test_auto_install_disabled_raises_with_hint(monkeypatch):
    monkeypatch.setattr(ss.settings, "browser_auto_install", False)
    with pytest.raises(ConfigurationError, match="playwright install chromium"):
        await _service()._launch_with_install("chromium", _Launcher([MISSING]))


@pytest.mark.asyncio
async def test_unrelated_launch_errors_are_not_swallowed(monkeypatch):
    async def boom(browser_type):  # pragma: no cover
        raise AssertionError("must not install")

    monkeypatch.setattr(ss, "install_playwright_browser", boom)
    with pytest.raises(RuntimeError, match="sandbox"):
        await _service()._launch_with_install(
            "chromium", _Launcher([RuntimeError("sandbox denied")])
        )


@pytest.mark.asyncio
async def test_still_missing_after_install_reports_clearly(monkeypatch):
    async def fake_install(browser_type):
        return None

    monkeypatch.setattr(ss, "install_playwright_browser", fake_install)
    monkeypatch.setattr(ss.settings, "browser_auto_install", True)
    with pytest.raises(ConfigurationError, match="still unavailable"):
        await _service()._launch_with_install("chromium", _Launcher([MISSING, MISSING]))
