"""YouTube transcript URL, track, parsing, storage, and HTTP tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controllers import youtube_controller
from core.foundation import SecurityMiddleware, get_youtube_transcript_service
from services.youtube_transcript_service import (
    TranscriptServiceError,
    YoutubeTranscriptService,
    canonicalize_youtube_url,
    parse_json3_segments,
    select_caption_track,
)
from services.fetch_service import FetchService


VIDEO_ID = "YE7VzlLtp-4"


class FakeCache:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True


class FakeFetch:
    def __init__(self):
        self.calls = 0

    async def request(self, **_kwargs):
        self.calls += 1
        raw = json.dumps(
            {
                "events": [
                    {
                        "tStartMs": 0,
                        "dDurationMs": 1200,
                        "segs": [{"utf8": "Hello  world"}],
                    },
                    {
                        "tStartMs": 1200,
                        "dDurationMs": 800,
                        "segs": [{"utf8": "Second line"}],
                    },
                ]
            }
        ).encode()
        return {"status": 200, "_content_bytes": raw}


class FakeDownloads:
    def __init__(self, root: Path):
        self.root = root
        self.calls = 0

    async def save_bytes(self, content, filename, **_kwargs):
        self.calls += 1
        path = self.root / filename
        path.write_bytes(content)
        return {
            "download_id": f"dl_{self.calls:012d}",
            "filename": filename,
            "path": str(path),
            "absolute_path": str(path),
            "size_bytes": len(content),
            "content_type": "text/markdown; charset=utf-8",
        }


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}&list=ignored",
        f"https://youtu.be/{VIDEO_ID}?t=3",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}",
    ],
)
def test_canonicalize_supported_single_video_urls(url):
    canonical, video_id = canonicalize_youtube_url(url)
    assert video_id == VIDEO_ID
    assert canonical == f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=YE7VzlLtp-4",
        "https://www.youtube.com/playlist?list=PL123",
        "https://user:pass@www.youtube.com/watch?v=YE7VzlLtp-4",
        "https://www.youtube.com/watch?v=short",
    ],
)
def test_canonicalize_rejects_unsupported_urls(url):
    with pytest.raises(TranscriptServiceError, match="YouTube"):
        canonicalize_youtube_url(url)


def test_track_selection_prefers_manual_for_requested_language():
    info = {
        "subtitles": {
            "en": [{"ext": "json3", "url": "https://captions.example/manual"}]
        },
        "automatic_captions": {
            "en": [{"ext": "json3", "url": "https://captions.example/auto"}]
        },
    }
    selected = select_caption_track(
        info, requested_languages=["en"], allow_auto_captions=True
    )
    assert selected["source"] == "manual"
    assert selected["url"].endswith("/manual")


def test_track_selection_uses_original_auto_and_not_translation():
    info = {
        "language": "hi",
        "automatic_captions": {
            "en": [{"ext": "json3", "url": "https://captions.example/en"}],
            "hi-orig": [
                {"ext": "json3", "url": "https://captions.example/hi"}
            ],
        },
    }
    selected = select_caption_track(
        info, requested_languages=[], allow_auto_captions=True
    )
    assert selected["source"] == "automatic"
    assert selected["language_code"] == "hi-orig"


def test_track_selection_honors_auto_caption_opt_out():
    info = {
        "language": "en",
        "automatic_captions": {
            "en-orig": [{"ext": "json3", "url": "https://captions.example/en"}]
        },
    }
    with pytest.raises(TranscriptServiceError) as exc_info:
        select_caption_track(
            info, requested_languages=[], allow_auto_captions=False
        )
    assert exc_info.value.code == "NO_TRANSCRIPT"


def test_track_selection_preserves_primary_manual_order_without_metadata():
    info = {
        "subtitles": {
            "en": [{"ext": "json3", "url": "https://captions.example/en"}],
            "de": [{"ext": "json3", "url": "https://captions.example/de"}],
        }
    }
    selected = select_caption_track(
        info, requested_languages=[], allow_auto_captions=True
    )
    assert selected["language_code"] == "en"


def test_json3_parser_normalizes_and_deduplicates():
    raw = json.dumps(
        {
            "events": [
                {
                    "tStartMs": 1000,
                    "dDurationMs": 500,
                    "segs": [{"utf8": " Hello\n"}, {"utf8": "&amp; welcome "}],
                },
                {
                    "tStartMs": 1500,
                    "dDurationMs": 500,
                    "segs": [{"utf8": "Hello & welcome"}],
                },
                {"tStartMs": 2000, "segs": [{"utf8": "   "}]},
            ]
        }
    ).encode()
    segments = parse_json3_segments(raw)
    assert len(segments) == 1
    assert segments[0].text == "Hello & welcome"
    assert segments[0].start_ms == 1000
    assert segments[0].end_ms == 2000


@pytest.mark.asyncio
async def test_service_bounds_inline_content_keeps_full_artifact_and_caches(
    tmp_path, monkeypatch
):
    fetch = FakeFetch()
    downloads = FakeDownloads(tmp_path)
    service = YoutubeTranscriptService(fetch, downloads, FakeCache())
    info_calls = 0

    def fake_info(_url):
        nonlocal info_calls
        info_calls += 1
        return {
            "id": VIDEO_ID,
            "title": "Example",
            "channel": "Channel",
            "duration": 2,
            "language": "en",
            "subtitles": {
                "en": [
                    {
                        "ext": "json3",
                        "url": "https://captions.example/manual",
                        "name": "English",
                    }
                ]
            },
        }

    monkeypatch.setattr(service, "_extract_info_sync", fake_info)
    first = await service.get_transcript(
        url=f"https://youtu.be/{VIDEO_ID}", max_text_length=10
    )
    second = await service.get_transcript(
        url=f"https://youtu.be/{VIDEO_ID}", max_text_length=10
    )

    assert first["truncated"] is True
    assert "truncated" in first["content"]
    artifact_text = Path(first["artifact"]["absolute_path"]).read_text()
    assert "Second line" in artifact_text
    assert first["artifact"]["content_url"].startswith("/downloads/dl_")
    # Second call must be served from cache: no new info extraction.
    assert info_calls == 1
    assert fetch.calls == 1
    assert downloads.calls == 2


def test_youtube_route_is_available_in_loopback_free_tier(tmp_path, monkeypatch):
    class FakeService:
        async def get_transcript(self, **_kwargs):
            return {
                "success": True,
                "video": {"id": VIDEO_ID},
                "track": {"language_code": "en", "source": "manual"},
                "content": "text",
                "truncated": False,
                "character_count": 4,
                "segment_count": 1,
                "artifact": {"download_id": "dl_123"},
                "cache_hit": False,
            }

    test_app = FastAPI()
    test_app.add_middleware(SecurityMiddleware)
    test_app.include_router(youtube_controller.router, prefix="/youtube")
    test_app.dependency_overrides[get_youtube_transcript_service] = lambda: FakeService()
    try:
        with TestClient(test_app, raise_server_exceptions=False) as client:
            response = client.post(
                "/youtube/transcript",
                json={"url": f"https://youtu.be/{VIDEO_ID}"},
            )
    finally:
        test_app.dependency_overrides.pop(get_youtube_transcript_service, None)

    assert response.status_code == 200
    assert response.json()["video"]["id"] == VIDEO_ID


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("SURF_RUN_YOUTUBE_INTEGRATION"),
    reason="set SURF_RUN_YOUTUBE_INTEGRATION=1 for live YouTube verification",
)
@pytest.mark.asyncio
async def test_live_public_youtube_transcript(tmp_path):
    service = YoutubeTranscriptService(
        FetchService(), FakeDownloads(tmp_path), FakeCache()
    )
    try:
        result = await service.get_transcript(
            url="https://www.youtube.com/watch?v=jNQXAC9IVRw",
            max_text_length=500,
        )
    except TranscriptServiceError as exc:
        if exc.code in {"VIDEO_UNAVAILABLE", "UPSTREAM_RATE_LIMITED"}:
            pytest.xfail(f"YouTube blocked the unauthenticated integration fixture: {exc.code}")
        raise
    assert result["video"]["id"] == "jNQXAC9IVRw"
    assert result["track"]["language_code"] == "en"
    assert len(result["content"]) > 0
    assert Path(result["artifact"]["absolute_path"]).is_file()
