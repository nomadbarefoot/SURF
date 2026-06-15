"""Unit tests for challenge resolver and search extract routing logic."""
from __future__ import annotations

import pytest

from services.challenge_resolver import ChallengeResolver


class TestChallengeDetection:
    def test_detects_cloudflare_title(self):
        assert ChallengeResolver.is_challenge_page("Just a moment...", "")

    def test_detects_checking_browser(self):
        assert ChallengeResolver.is_challenge_page("", "Checking your browser before accessing")

    def test_clean_page(self):
        assert not ChallengeResolver.is_challenge_page(
            "India Bond Outlook 2026",
            "The debt market is expected to remain stable with RBI policy support.",
        )


class TestRetryRouting:
    def test_retryable_on_unavailable(self):
        assert ChallengeResolver.is_retryable_failure({"success": False, "error": "Page unavailable"})

    def test_retryable_on_timeout(self):
        assert ChallengeResolver.is_retryable_failure({"success": False, "error": "Global timeout"})

    def test_not_retryable_on_success(self):
        assert not ChallengeResolver.is_retryable_failure({"success": True})

    def test_headed_retry_requires_relevance(self):
        result = {"success": False, "error": "Page unavailable", "challenge_blocked": True}
        url = "https://example.com/article"
        assert not ChallengeResolver.should_headed_retry(url, result, None)
        assert not ChallengeResolver.should_headed_retry(url, result, {url: 0.5})
        assert ChallengeResolver.should_headed_retry(url, result, {url: 0.9})

    def test_detects_robot_challenge_title(self):
        assert ChallengeResolver.is_challenge_page("Robot Challenge Screen", "")

    def test_agent_error_is_neutral(self):
        assert ChallengeResolver.agent_error() == "Page unavailable"


class TestPublicResultSanitization:
    def test_public_result_hides_challenge_detail(self):
        from services.search_service import SearchService

        raw = {
            "url": "https://example.com",
            "success": False,
            "error": "Bot protection wall",
            "challenge_blocked": True,
            "ms": 1200,
        }
        public = SearchService._public_result(raw)
        assert public["error"] == "Page unavailable"
        assert "challenge" not in public["error"].lower()
