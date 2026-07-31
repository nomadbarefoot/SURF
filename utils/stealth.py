"""Stealth patch bundles scoped by strategy.

Patch bundles are applied at context creation time. The default is minimal:
only low-risk automation cleanup. Balanced and aggressive add more consistency
patches but avoid hard-coded timezone/platform/screen/plugin/canvas spoofing
unless explicitly requested via the aggressive profile.
"""
from __future__ import annotations

import asyncio
import random
from typing import Dict, Any, Optional

from playwright.async_api import Page

import structlog

logger = structlog.get_logger()


_MINIMAL_PATCH = """
() => {
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });
}
"""

_BALANCED_PATCH = """
() => {
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });

    // Remove Playwright/ChromeDriver automation globals.
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

    // permissions.query returns the real answer except for notifications,
    // where some automation frameworks leak a 'prompt' state.
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters)
    );

    // Consistent connection API if the browser exposes it.
    if ('connection' in navigator) {
        Object.defineProperty(navigator, 'connection', {
            get: () => ({
                effectiveType: '4g',
                rtt: 50,
                downlink: 10,
            }),
        });
    }
}
"""

_AGGRESSIVE_PATCH = """
() => {
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });

    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters)
    );

    Object.defineProperty(navigator, 'mediaDevices', {
        get: () => ({
            enumerateDevices: () => Promise.resolve([]),
            getUserMedia: () => Promise.reject(new Error('Permission denied')),
        }),
    });

    Object.defineProperty(navigator, 'geolocation', {
        get: () => ({
            getCurrentPosition: () => Promise.reject(new Error('Permission denied')),
            watchPosition: () => Promise.reject(new Error('Permission denied')),
            clearWatch: () => {},
        }),
    });

    Object.defineProperty(navigator, 'getBattery', {
        get: () => () => Promise.resolve({
            charging: true,
            chargingTime: 0,
            dischargingTime: Infinity,
            level: 1,
        }),
    });

    Object.defineProperty(navigator, 'connection', {
        get: () => ({
            effectiveType: '4g',
            rtt: 50,
            downlink: 10,
        }),
    });

    // WebGL vendor/renderer: keep consistent with the bundled Chromium but
    // override the headless "Google Inc. (NVIDIA)" / "ANGLE" defaults that
    // leak automation.
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) {
            return 'Intel Inc.';
        }
        if (parameter === 37446) {
            return 'Intel Iris Xe Graphics';
        }
        return getParameter(parameter);
    };

    // Audio context: add imperceptible noise to fingerprinting reads.
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (AudioContext) {
        const originalCreateAnalyser = AudioContext.prototype.createAnalyser;
        AudioContext.prototype.createAnalyser = function() {
            const analyser = originalCreateAnalyser.call(this);
            const originalGetFloatFrequencyData = analyser.getFloatFrequencyData;
            analyser.getFloatFrequencyData = function(array) {
                originalGetFloatFrequencyData.call(this, array);
                for (let i = 0; i < array.length; i++) {
                    array[i] += Math.random() * 0.0001;
                }
            };
            return analyser;
        };
    }
}
"""


def _bundle_for(strategy: str) -> str:
    strategy = (strategy or "minimal").lower()
    if strategy == "none":
        return ""
    if strategy == "balanced":
        return _BALANCED_PATCH
    if strategy == "aggressive":
        return _AGGRESSIVE_PATCH
    if strategy == "legacy":
        return _AGGRESSIVE_PATCH
    return _MINIMAL_PATCH


async def setup_stealth_mode(page: Page, strategy: str = "minimal") -> None:
    """Apply a named stealth patch bundle to the page."""
    bundle = _bundle_for(strategy)
    if not bundle:
        return
    try:
        await page.add_init_script(bundle)
        logger.debug("stealth_bundle_applied", strategy=strategy)
    except Exception as e:
        logger.error("Failed to setup stealth mode", strategy=strategy, error=str(e))


async def apply_human_behavior(
    page: Page,
    scroll_pauses: int = 2,
    mouse_movements: bool = True,
) -> None:
    """Apply scoped human-like behavior for challenge handling or soft walls.

    This is intentionally not called during ordinary navigation; enable it only
    when a profile's human_behavior.enabled is true.
    """
    try:
        if mouse_movements:
            await _random_mouse_movement(page)
        await _simulate_reading_behavior(page, scroll_pauses=scroll_pauses)
        logger.debug("human_behavior_applied", scroll_pauses=scroll_pauses)
    except Exception as e:
        logger.error("Failed to apply human behavior", error=str(e))


async def _random_mouse_movement(page: Page) -> None:
    viewport = page.viewport_size
    if not viewport:
        return
    for _ in range(random.randint(2, 4)):
        x = random.randint(0, viewport["width"])
        y = random.randint(0, viewport["height"])
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.05, 0.15))


async def _simulate_reading_behavior(page: Page, scroll_pauses: int = 2) -> None:
    for _ in range(scroll_pauses):
        await page.mouse.wheel(0, random.randint(200, 500))
        await asyncio.sleep(random.uniform(0.5, 1.5))
    if random.random() < 0.3:
        await page.mouse.wheel(0, -random.randint(100, 300))
        await asyncio.sleep(random.uniform(0.3, 0.8))


# Keep legacy exports for compatibility.
async def simulate_human_behavior(page: Page) -> None:
    """Legacy entrypoint; now scopes behavior to a single invocation."""
    await apply_human_behavior(page)


async def enhance_stealth_mode(page: Page) -> None:
    """Legacy entrypoint; applies the aggressive bundle."""
    await setup_stealth_mode(page, strategy="aggressive")


def get_random_headers(referer: str = None) -> Dict[str, str]:
    """Legacy: return a generic browser header set."""
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def get_realistic_headers(referer: str = None) -> Dict[str, str]:
    """Legacy: return a slightly varied header set."""
    headers = dict(get_random_headers(referer))
    headers["Sec-Fetch-Dest"] = "document"
    headers["Sec-Fetch-Mode"] = "navigate"
    headers["Sec-Fetch-Site"] = "none"
    return headers
