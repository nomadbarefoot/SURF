"""Version pins that must move together stay in sync."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pin(name: str) -> str:
    text = (ROOT / "requirements.txt").read_text()
    match = re.search(rf"^{re.escape(name)}(?:\[[^\]]*\])?==(\S+)$", text, re.M)
    assert match, f"{name} is not pinned in requirements.txt"
    return match.group(1)


def _floor(name: str) -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(rf'"{re.escape(name)}(?:\[[^\]]*\])?>=([^,"]+)', text)
    assert match, f"{name} has no >= floor in pyproject.toml"
    return match.group(1)


def test_playwright_pip_pin_matches_docker_base_image():
    # The image ships browsers for exactly one Playwright release.
    dockerfile = (ROOT / "Dockerfile").read_text()
    image = re.search(r"playwright/python:v(\d+\.\d+\.\d+)", dockerfile)
    assert image, "Dockerfile base image is not playwright/python"
    assert _pin("playwright") == image.group(1)
    assert _floor("playwright") == image.group(1)


def test_yt_dlp_floor_matches_docker_pin():
    # Package installs must never resolve an older yt-dlp than the image ships.
    assert _floor("yt-dlp") == _pin("yt-dlp")
