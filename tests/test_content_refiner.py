"""Unit tests for structured content refinement."""
from __future__ import annotations

import pytest

from services.content_refiner import (
    ContentRefiner,
    blocks_to_sections,
    is_noise_block,
    sections_to_markdown,
)


def test_noise_block_detects_disclaimer():
    assert is_noise_block({"type": "paragraph", "text": "Disclaimer: not financial advice."})


def test_noise_block_keeps_substantive_paragraph():
    assert not is_noise_block(
        {
            "type": "paragraph",
            "text": "BSE Sensex closed at 83,817.69 on February 4, 2026, up slightly by 0.09%.",
        }
    )


def test_blocks_to_sections_groups_under_headings():
    blocks = [
        {"type": "heading", "level": 2, "text": "Indian Market Overview"},
        {"type": "paragraph", "text": "Sensex closed higher amid mixed global cues."},
        {"type": "heading", "level": 2, "text": "Key Economic Drivers"},
        {"type": "paragraph", "text": "GDP growth for FY26 is estimated at 7.4%."},
        {"type": "paragraph", "text": "Related Stories"},
    ]
    sections = blocks_to_sections(blocks)
    assert len(sections) == 2
    assert sections[0]["heading"] == "Indian Market Overview"
    assert len(sections[0]["blocks"]) == 1
    assert sections[1]["heading"] == "Key Economic Drivers"


def test_sections_to_markdown_renders_headings_and_table():
    sections = [
        {
            "heading": "Overview",
            "level": 2,
            "blocks": [
                {"type": "paragraph", "text": "Markets were mixed."},
                {
                    "type": "table",
                    "rows": [["Date", "Close"], ["Feb 4", "83817"]],
                },
            ],
        }
    ]
    md = sections_to_markdown("Title", sections, "https://example.com")
    assert "# Title" in md
    assert "## Overview" in md
    assert "| Date | Close |" in md
    assert "*Source: https://example.com*" in md


@pytest.mark.asyncio
async def test_refiner_without_query():
    structured = {
        "title": "Sample",
        "url": "https://example.com",
        "blocks": [
            {"type": "heading", "level": 2, "text": "Outlook"},
            {"type": "paragraph", "text": "Nifty may reach 29000 by year end according to analysts."},
        ],
    }
    out = await ContentRefiner.refine(structured, query=None)
    assert out["section_count"] == 1
    assert "Nifty may reach" in out["markdown"]
    assert out["chars"] > 50
