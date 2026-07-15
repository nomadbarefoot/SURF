"""Durability tests for research ETL artifacts."""
from __future__ import annotations

from scripts.run_research_etl import _atomic_write_text


def test_atomic_write_replaces_existing_artifact(tmp_path):
    destination = tmp_path / "run.json"
    destination.write_text("old", encoding="utf-8")

    _atomic_write_text(destination, "new")

    assert destination.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob("*.tmp")) == []
