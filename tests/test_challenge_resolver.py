"""Unit tests for challenge resolver and search extract routing logic."""
from __future__ import annotations

import pytest

from services.challenge_resolver import ChallengeResolver, LadderConfig


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

    def test_detects_robot_challenge_title(self):
        assert ChallengeResolver.is_challenge_page("Robot Challenge Screen", "")

    def test_agent_error_is_neutral(self):
        assert ChallengeResolver.agent_error() == "Page unavailable"


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


# ---------------------------------------------------------------------------
# Bounded state-machine tests
# ---------------------------------------------------------------------------


class FakePage:
    """Minimal fake Playwright page for challenge resolver tests."""

    def __init__(self, title_text="Welcome", body_text="Some content here", cookies=None):
        self._title = title_text
        self._body = body_text
        self._cookies = cookies or []
        self.reload_calls = 0
        self.clicked = False
        self.context = FakeContext(self._cookies)

    async def title(self):
        return self._title

    async def evaluate(self, script):
        if script == "() => (document.body?.innerText || '').slice(0, 3000)":
            return self._body[:3000]
        if script == "() => (document.body?.innerText || '').slice(0, 2000).toLowerCase()":
            return self._body[:2000].lower()
        if script == "() => (document.body?.innerText || '').length":
            return len(self._body)
        return None

    async def reload(self, **kwargs):
        self.reload_calls += 1
        # Simulate challenge clearing on reload.
        self._title = "Welcome"
        self._body = "Cleared content " * 100

    @property
    def url(self):
        return "https://example.com"

    def locator(self, selector):
        return FakeLocator(self, selector)

    @property
    def mouse(self):
        return FakeMouse(self)


class FakeContext:
    def __init__(self, cookies):
        self._cookies = cookies

    async def cookies(self):
        return self._cookies

    async def add_cookies(self, cookies):
        self._cookies.extend(cookies)


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    async def count(self):
        if "checkbox" in self.selector:
            return 1
        return 0

    @property
    def first(self):
        return self

    async def bounding_box(self):
        if "checkbox" in self.selector:
            return {"x": 100, "y": 100, "width": 20, "height": 20}
        return None

    async def click(self):
        self.page.clicked = True


class FakeMouse:
    def __init__(self, page):
        self.page = page

    async def move(self, x, y):
        pass

    async def click(self, x, y):
        self.page.clicked = True
        # Simulate checkbox click clearing challenge after short delay would be
        # handled by wait_passive, so we pre-clear the page here.
        self.page._title = "Welcome"
        self.page._body = "Cleared content " * 100


@pytest.mark.asyncio
async def test_cleared_when_no_challenge_markers():
    page = FakePage("Article", "Real article content " * 100)
    resolver = ChallengeResolver(page)
    result = await resolver.run()
    assert result.state == "cleared"
    assert not result.blocked


@pytest.mark.asyncio
async def test_challenge_detected_then_passive_clears():
    page = FakePage("Just a moment...", "Checking your browser...")
    resolver = ChallengeResolver(page, ladder=LadderConfig(passive_wait_ms=200, max_passive_attempts=2))

    async def wait_passive(timeout_ms):
        page._title = "Welcome"
        page._body = "Cleared content " * 100
        return True

    resolver._wait_passive = wait_passive
    result = await resolver.run()
    assert result.state == "passive"
    assert not result.blocked
    assert result.type == "cloudflare"


@pytest.mark.asyncio
async def test_challenge_exhausts_and_returns_manual_required():
    page = FakePage("Just a moment...", "Checking your browser...")
    resolver = ChallengeResolver(page, ladder=LadderConfig(passive_wait_ms=50, max_passive_attempts=1))
    result = await resolver.run()
    assert result.state == "manual_required"
    assert result.blocked
    assert result.type == "cloudflare"


@pytest.mark.asyncio
async def test_checkbox_assist_clears_challenge():
    page = FakePage("Just a moment...", "Checking your browser...")
    resolver = ChallengeResolver(
        page,
        ladder=LadderConfig(
            passive_wait_ms=50,
            max_passive_attempts=1,
            allow_checkbox_assist=True,
        ),
    )
    result = await resolver.run()
    assert result.state == "clicked"
    assert not result.blocked
    assert page.clicked


@pytest.mark.asyncio
async def test_reload_clears_challenge():
    page = FakePage("Just a moment...", "Checking your browser...")
    resolver = ChallengeResolver(
        page,
        ladder=LadderConfig(
            passive_wait_ms=50,
            max_passive_attempts=1,
            allow_reload=True,
        ),
    )
    result = await resolver.run()
    assert result.state == "reload"
    assert not result.blocked
    assert page.reload_calls == 1


@pytest.mark.asyncio
async def test_classify_returns_type_and_indicators():
    challenge_type, indicators = ChallengeResolver.classify(
        "Just a moment...", "Checking your browser by Cloudflare"
    )
    assert challenge_type == "cloudflare"
    assert "cloudflare" in indicators
    assert "just a moment" in indicators


@pytest.mark.asyncio
async def test_resolve_headed_wrapper():
    page = FakePage("Just a moment...", "Checking your browser...")

    async def wait_passive(timeout_ms):
        page._title = "Welcome"
        page._body = "Cleared " * 100
        return True

    # Patch on a fresh resolver created inside resolve_headed is not easy, so
    # we test the state machine path directly.
    resolver = ChallengeResolver(page)
    resolver._wait_passive = wait_passive
    result = await resolver.run()
    assert result.state == "passive"


class TestClassifierPrecision:
    """Ambiguous vendor mentions must not be mistaken for real gates.

    Bare markers like "cloudflare" or "blocked" appear constantly in ordinary
    prose; treating them as challenges made the browse ladder burn its full
    budget and report success=False for perfectly readable pages.
    """

    LONG_ARTICLE = (
        "Cloudflare reported revenue growth this quarter, and analysts covering "
        "the CDN and security market noted that hCaptcha and reCAPTCHA adoption "
        "continues to expand across the industry. " * 20
    )

    def test_article_about_cloudflare_is_not_a_challenge(self):
        assert not ChallengeResolver.is_challenge_page(
            "Cloudflare Q3 earnings beat estimates", self.LONG_ARTICLE
        )

    def test_word_blocked_in_long_prose_is_not_a_challenge(self):
        text = (
            "Some users were blocked by an incorrect firewall rule during the "
            "incident window, and we have since corrected the configuration. " * 20
        )
        assert not ChallengeResolver.is_challenge_page("Incident status", text)

    def test_strong_marker_still_detected_in_long_page(self):
        assert ChallengeResolver.is_challenge_page(
            "Just a moment...", self.LONG_ARTICLE
        )

    def test_weak_marker_counts_on_short_interstitial(self):
        challenge_type, indicators = ChallengeResolver.classify(
            "Attention", "cloudflare"
        )
        assert challenge_type == "cloudflare"
        assert "cloudflare" in indicators

    def test_weak_marker_counts_when_widget_present(self):
        challenge_type, _ = ChallengeResolver.classify(
            "News", self.LONG_ARTICLE, has_challenge_widget=True
        )
        assert challenge_type is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,expected",
    [
        ("cleared", "passive"),
        ("passive", "passive"),
        ("clicked", "clicked"),
        ("reload", "clicked"),
        ("manual_required", "timeout"),
    ],
)
async def test_resolve_headed_state_mapping(monkeypatch, state, expected):
    """A cleared checkbox challenge must not be reported as a timeout."""
    from services.challenge_resolver import ChallengeResult

    async def fake_run(self):
        return ChallengeResult(state=state, blocked=(state == "manual_required"))

    monkeypatch.setattr(ChallengeResolver, "run", fake_run)
    assert await ChallengeResolver.resolve_headed(FakePage()) == expected


def test_resolver_reads_the_attribute_browse_service_writes():
    """Guards against dunder name mangling silently severing the link.

    ``page.__surf_session = s`` inside a class body becomes
    ``_BrowseService__surf_session``, which the resolver never finds — the
    challenge screenshot and blocker-relaxation paths then go dead silently.
    """
    import inspect

    from services.browse_service import BrowseService

    source = inspect.getsource(BrowseService.browse)
    assert "page._surf_session = session" in source
    assert "page.__surf_session" not in source

    class Page:
        pass

    page = Page()
    page._surf_session = "SESSION"
    resolver = ChallengeResolver.__new__(ChallengeResolver)
    resolver.page = page
    assert resolver._session_for_page() == "SESSION"


@pytest.mark.asyncio
async def test_headed_retry_always_closes_its_session():
    """The headed session owns a real browser window and must be reclaimed."""
    closed = []

    class FakeSessionService:
        async def create_session(self, user_config=None, pool=None):
            class S:
                session_id = "sess_headed_1"
                # Already clear, so the sub-resolver returns immediately rather
                # than burning its hardcoded 3 x 30s passive budget.
                page = FakePage("Welcome", "Real article content " * 100)

            return S()

        async def close_session(self, session_id):
            closed.append(session_id)

    class FakeBrowserService:
        async def navigate_to_url(self, session=None, url=None, timeout=None):
            return {"success": True}

    resolver = ChallengeResolver(
        FakePage("Just a moment...", "Checking your browser..."),
        ladder=LadderConfig(
            passive_wait_ms=1,
            max_passive_attempts=1,
            allow_headed_retry=True,
            max_total_attempts=2,
        ),
        browser_service=FakeBrowserService(),
        session_service=FakeSessionService(),
    )
    await resolver._headed_retry("cloudflare", ["just a moment"])
    assert closed == ["sess_headed_1"]
