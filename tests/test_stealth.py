"""Tests for stealth patch bundles."""
import pytest

from utils.stealth import _bundle_for, setup_stealth_mode


class FakePage:
    def __init__(self):
        self.scripts = []

    async def add_init_script(self, script):
        self.scripts.append(script)


@pytest.mark.asyncio
async def test_minimal_bundle_applies_webdriver_patch():
    page = FakePage()
    await setup_stealth_mode(page, strategy="minimal")
    assert len(page.scripts) == 1
    assert "webdriver" in page.scripts[0]


@pytest.mark.asyncio
async def test_balanced_bundle_includes_cdc_cleanup():
    page = FakePage()
    await setup_stealth_mode(page, strategy="balanced")
    assert "cdc_adoQpoasnfa76pfcZLmcfl_Array" in page.scripts[0]


@pytest.mark.asyncio
async def test_aggressive_bundle_includes_webgl_override():
    page = FakePage()
    await setup_stealth_mode(page, strategy="aggressive")
    assert "WebGLRenderingContext" in page.scripts[0]


@pytest.mark.asyncio
async def test_none_strategy_applies_nothing():
    page = FakePage()
    await setup_stealth_mode(page, strategy="none")
    assert page.scripts == []


def test_unknown_strategy_falls_back_to_minimal():
    bundle = _bundle_for("weird")
    assert "webdriver" in bundle
    assert "WebGLRenderingContext" not in bundle


def test_legacy_strategy_maps_to_aggressive():
    bundle = _bundle_for("legacy")
    assert "WebGLRenderingContext" in bundle
