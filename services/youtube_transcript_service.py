"""YouTube caption acquisition and transcript normalization."""

from __future__ import annotations

import asyncio
import hashlib
import html
import importlib.metadata
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional
from urllib.parse import parse_qs, urlsplit

import structlog

from config import get_settings
from core.foundation import BrowserOperationError, ResourceLimitError
from models.schemas import FetchBackend
from services.cache_service import CacheService
from services.download_service import DownloadService
from services.fetch_service import FetchService
from utils.url_security import safe_url_for_log

logger = structlog.get_logger()
settings = get_settings()

_VIDEO_ID_RE = re.compile(r"^[0-9A-Za-z_-]{11}$")
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtu.be",
    "www.youtu.be",
}


class TranscriptServiceError(Exception):
    """Stable transcript failure exposed by HTTP, MCP, and CLI."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 502,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


@dataclass(frozen=True)
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class TranscriptDocument:
    video: Dict[str, Any]
    track: Dict[str, Any]
    segments: tuple[TranscriptSegment, ...]
    retrieved_at: str

    def to_cache(self) -> Dict[str, Any]:
        return {
            "video": self.video,
            "track": self.track,
            "segments": [asdict(segment) for segment in self.segments],
            "retrieved_at": self.retrieved_at,
        }

    @classmethod
    def from_cache(cls, value: Dict[str, Any]) -> "TranscriptDocument":
        return cls(
            video=dict(value["video"]),
            track=dict(value["track"]),
            segments=tuple(
                TranscriptSegment(
                    start_ms=int(segment["start_ms"]),
                    end_ms=int(segment["end_ms"]),
                    text=str(segment["text"]),
                )
                for segment in value["segments"]
            ),
            retrieved_at=str(value["retrieved_at"]),
        )


class YoutubeTranscriptService:
    """Acquire one public YouTube caption track and publish a Markdown artifact."""

    def __init__(
        self,
        fetch_service: FetchService,
        download_service: DownloadService,
        cache_service: CacheService,
    ) -> None:
        self.fetch_service = fetch_service
        self.download_service = download_service
        self.cache_service = cache_service
        self._semaphore = asyncio.Semaphore(settings.youtube_transcript_concurrency)

    async def get_transcript(
        self,
        *,
        url: str,
        languages: Optional[list[str]] = None,
        allow_auto_captions: bool = True,
        max_text_length: int = 20000,
    ) -> Dict[str, Any]:
        canonical_url, video_id = canonicalize_youtube_url(url)
        requested_languages = _normalize_requested_languages(languages)
        cache_key = self._cache_key(
            video_id, requested_languages, allow_auto_captions
        )

        document = await self._get_cached(cache_key)
        cache_hit = document is not None
        if document is None:
            async with self._semaphore:
                document = await self._acquire(
                    canonical_url=canonical_url,
                    requested_languages=requested_languages,
                    allow_auto_captions=allow_auto_captions,
                )
            await self._set_cached(cache_key, document)

        body = render_transcript_body(document.segments)
        markdown = render_transcript_markdown(document)
        language_code = _safe_slug(str(document.track["language_code"]))
        artifact = await self.download_service.save_bytes(
            markdown.encode("utf-8"),
            filename=f"{video_id}-{language_code}-transcript.md",
            source_url=canonical_url,
            content_type="text/markdown; charset=utf-8",
        )
        artifact["content_url"] = (
            f"/downloads/{artifact['download_id']}/content"
        )

        truncated = len(body) > max_text_length
        content = body[:max_text_length]
        if truncated:
            content = content.rstrip() + "\n\n[Transcript truncated; use artifact for full text.]"

        return {
            "success": True,
            "video": document.video,
            "track": document.track,
            "content": content,
            "truncated": truncated,
            "artifact": artifact,
        }

    async def _acquire(
        self,
        *,
        canonical_url: str,
        requested_languages: list[str],
        allow_auto_captions: bool,
    ) -> TranscriptDocument:
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(self._extract_info_sync, canonical_url),
                timeout=settings.youtube_transcript_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise TranscriptServiceError(
                "TRANSCRIPT_TIMEOUT",
                "YouTube transcript extraction timed out",
                status_code=504,
            ) from exc
        except TranscriptServiceError:
            raise
        except Exception as exc:
            raise self._map_extractor_error(exc) from exc

        if info.get("live_status") in {"is_live", "is_upcoming"}:
            raise TranscriptServiceError(
                "VIDEO_UNAVAILABLE",
                "Live and upcoming YouTube videos are not supported",
                status_code=409,
            )

        track = select_caption_track(
            info,
            requested_languages=requested_languages,
            allow_auto_captions=allow_auto_captions,
        )
        try:
            response = await self.fetch_service.request(
                method="GET",
                url=str(track["url"]),
                headers=dict(
                    track.get("http_headers") or info.get("http_headers") or {}
                ),
                timeout=int(settings.youtube_transcript_timeout_seconds * 1000),
                backend=FetchBackend.HTTPX,
            )
        except ResourceLimitError as exc:
            raise TranscriptServiceError(
                "TRANSCRIPT_TOO_LARGE",
                "Caption payload exceeds the configured limit",
                status_code=413,
                details=exc.details,
            ) from exc
        except BrowserOperationError as exc:
            if "timeout" in exc.message.lower():
                raise TranscriptServiceError(
                    "TRANSCRIPT_TIMEOUT",
                    "YouTube caption download timed out",
                    status_code=504,
                ) from exc
            raise TranscriptServiceError(
                "TRANSCRIPT_EXTRACTION_FAILED",
                "YouTube caption download failed",
                status_code=502,
            ) from exc
        status = int(response.get("status") or 0)
        if status == 429:
            raise TranscriptServiceError(
                "UPSTREAM_RATE_LIMITED",
                "YouTube rate-limited the caption request",
                status_code=429,
            )
        if status < 200 or status >= 300:
            raise TranscriptServiceError(
                "TRANSCRIPT_EXTRACTION_FAILED",
                f"Caption download returned HTTP {status}",
                status_code=502,
            )

        raw = response.get("_content_bytes") or b""
        if len(raw) > settings.youtube_transcript_max_caption_bytes:
            raise TranscriptServiceError(
                "TRANSCRIPT_TOO_LARGE",
                "Caption payload exceeds the configured limit",
                status_code=413,
                details={
                    "limit": settings.youtube_transcript_max_caption_bytes,
                    "current": len(raw),
                },
            )
        segments = parse_json3_segments(raw)
        if len(segments) > settings.youtube_transcript_max_segments:
            raise TranscriptServiceError(
                "TRANSCRIPT_TOO_LARGE",
                "Caption segment count exceeds the configured limit",
                status_code=413,
                details={
                    "limit": settings.youtube_transcript_max_segments,
                    "current": len(segments),
                },
            )
        if not segments:
            raise TranscriptServiceError(
                "NO_TRANSCRIPT",
                "The selected caption track contained no transcript text",
                status_code=404,
            )

        video_id = str(info.get("id") or canonical_url.rsplit("=", 1)[-1])
        video = {
            "id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": str(info.get("title") or ""),
            "channel": str(info.get("channel") or info.get("uploader") or ""),
            "duration_seconds": _optional_int(info.get("duration")),
            "upload_date": info.get("upload_date"),
        }
        public_track = {
            "language_code": track["language_code"],
            "language_name": track.get("language_name") or track["language_code"],
            "source": track["source"],
        }
        return TranscriptDocument(
            video=video,
            track=public_track,
            segments=tuple(segments),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _extract_info_sync(url: str) -> Dict[str, Any]:
        try:
            import yt_dlp
        except ImportError as exc:
            raise TranscriptServiceError(
                "TRANSCRIPT_DEPENDENCY_UNAVAILABLE",
                "yt-dlp is not installed",
                status_code=503,
            ) from exc

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "ignoreconfig": True,
            "socket_timeout": settings.youtube_transcript_timeout_seconds,
            "retries": 1,
            "extractor_args": {
                "youtube": {"skip": ["hls", "dash", "translated_subs"]}
            },
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            extracted = ydl.extract_info(url, download=False)
            info = ydl.sanitize_info(extracted)
        if not isinstance(info, dict) or info.get("_type") == "playlist":
            raise TranscriptServiceError(
                "INVALID_YOUTUBE_URL",
                "A single YouTube video URL is required",
                status_code=400,
            )
        return info

    @staticmethod
    def _map_extractor_error(exc: Exception) -> TranscriptServiceError:
        message = str(exc)
        lowered = message.lower()
        safe_message = "YouTube video metadata could not be retrieved"
        if "private video" in lowered or "sign in" in lowered or "age" in lowered:
            return TranscriptServiceError(
                "VIDEO_UNAVAILABLE", safe_message, status_code=403
            )
        if "429" in lowered or "too many requests" in lowered:
            return TranscriptServiceError(
                "UPSTREAM_RATE_LIMITED",
                "YouTube rate-limited the metadata request",
                status_code=429,
            )
        if "unavailable" in lowered or "not available" in lowered:
            return TranscriptServiceError(
                "VIDEO_UNAVAILABLE", safe_message, status_code=404
            )
        logger.warning(
            "youtube_transcript_metadata_failed",
            url=safe_url_for_log("https://www.youtube.com"),
            error_type=type(exc).__name__,
        )
        return TranscriptServiceError(
            "TRANSCRIPT_EXTRACTION_FAILED", safe_message, status_code=502
        )

    async def _get_cached(self, key: str) -> Optional[TranscriptDocument]:
        try:
            value = await self.cache_service.get(key)
            if isinstance(value, dict):
                return TranscriptDocument.from_cache(value)
        except Exception as exc:
            logger.warning("youtube_transcript_cache_get_failed", error=str(exc))
        return None

    async def _set_cached(self, key: str, document: TranscriptDocument) -> None:
        try:
            await self.cache_service.set(
                key,
                document.to_cache(),
                ttl=settings.youtube_transcript_cache_ttl_seconds,
            )
        except Exception as exc:
            logger.warning("youtube_transcript_cache_set_failed", error=str(exc))

    @staticmethod
    def _cache_key(
        video_id: str, languages: list[str], allow_auto_captions: bool
    ) -> str:
        signature = json.dumps(
            {
                "video_id": video_id,
                "languages": languages,
                "allow_auto_captions": allow_auto_captions,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        return f"youtube_transcript:v1:{digest}"

    @staticmethod
    def dependency_status() -> Dict[str, Any]:
        try:
            version = importlib.metadata.version("yt-dlp")
        except importlib.metadata.PackageNotFoundError:
            version = None
        deno_path = shutil.which("deno")
        if deno_path is None:
            try:
                import deno

                deno_path = deno.find_deno_bin()
            except (ImportError, OSError):
                deno_path = None
        return {
            "available": version is not None,
            "yt_dlp_version": version,
            "deno_available": deno_path is not None,
        }


def canonicalize_youtube_url(url: str) -> tuple[str, str]:
    """Return a canonical watch URL and video ID for one supported YouTube URL."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise TranscriptServiceError(
            "INVALID_YOUTUBE_URL", "Invalid YouTube URL", status_code=400
        ) from exc
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme not in {"http", "https"}
        or host not in _YOUTUBE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        raise TranscriptServiceError(
            "INVALID_YOUTUBE_URL",
            "A supported public YouTube video URL is required",
            status_code=400,
        )

    parts = [part for part in parsed.path.split("/") if part]
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"} and parts:
        video_id = parts[0]
    elif parsed.path.rstrip("/") == "/watch":
        video_id = (parse_qs(parsed.query).get("v") or [""])[0]
    elif len(parts) == 2 and parts[0] in {"shorts", "embed", "live", "v"}:
        video_id = parts[1]

    if not _VIDEO_ID_RE.fullmatch(video_id):
        raise TranscriptServiceError(
            "INVALID_YOUTUBE_URL",
            "A single YouTube video URL with a valid video ID is required",
            status_code=400,
        )
    return f"https://www.youtube.com/watch?v={video_id}", video_id


def select_caption_track(
    info: Dict[str, Any],
    *,
    requested_languages: list[str],
    allow_auto_captions: bool,
) -> Dict[str, Any]:
    manual = _json3_tracks(info.get("subtitles"))
    automatic = (
        _json3_tracks(info.get("automatic_captions"))
        if allow_auto_captions
        else {}
    )

    for requested in requested_languages:
        for source, tracks in (("manual", manual), ("automatic", automatic)):
            matched = _match_language(requested, tracks)
            if matched:
                return _public_track(matched, tracks[matched], source)

    if requested_languages:
        raise TranscriptServiceError(
            "LANGUAGE_UNAVAILABLE",
            "No usable caption track matched the requested languages",
            status_code=404,
            details={"requested_languages": requested_languages},
        )

    metadata_originals = [
        str(value)
        for value in (info.get("language"), info.get("original_language"))
        if value
    ]
    for original in metadata_originals:
        matched = _match_language(original, manual)
        if matched:
            return _public_track(matched, manual[matched], "manual")

    original_auto = sorted(
        code for code in automatic if code.lower().endswith("-orig")
    )
    for original in metadata_originals:
        base = original.lower().replace("_", "-").split("-", 1)[0]
        matched = next(
            (
                code
                for code in original_auto
                if code.lower().replace("_", "-").split("-", 1)[0] == base
            ),
            None,
        )
        if matched:
            return _public_track(matched, automatic[matched], "automatic")
    if original_auto:
        code = original_auto[0]
        return _public_track(code, automatic[code], "automatic")
    for original in metadata_originals:
        matched = _match_language(original, automatic)
        if matched:
            return _public_track(matched, automatic[matched], "automatic")

    if manual:
        # yt-dlp preserves YouTube's track order; the primary/original manual
        # track is first when language metadata is absent.
        code = next(iter(manual))
        return _public_track(code, manual[code], "manual")
    if len(automatic) == 1:
        code = next(iter(automatic))
        return _public_track(code, automatic[code], "automatic")
    raise TranscriptServiceError(
        "NO_TRANSCRIPT",
        "No usable original-language caption track is available",
        status_code=404,
    )


def parse_json3_segments(raw: bytes) -> list[TranscriptSegment]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranscriptServiceError(
            "TRANSCRIPT_EXTRACTION_FAILED",
            "YouTube returned an invalid caption payload",
            status_code=502,
        ) from exc

    segments: list[TranscriptSegment] = []
    for event in payload.get("events") or []:
        pieces = event.get("segs") or []
        text = "".join(str(piece.get("utf8") or "") for piece in pieces)
        text = re.sub(r"\s+", " ", html.unescape(text)).strip()
        if not text:
            continue
        start_ms = max(0, _optional_int(event.get("tStartMs")) or 0)
        duration_ms = max(0, _optional_int(event.get("dDurationMs")) or 0)
        end_ms = start_ms + duration_ms
        if segments and segments[-1].text == text:
            previous = segments[-1]
            segments[-1] = TranscriptSegment(
                start_ms=previous.start_ms,
                end_ms=max(previous.end_ms, end_ms),
                text=previous.text,
            )
            continue
        segments.append(
            TranscriptSegment(start_ms=start_ms, end_ms=end_ms, text=text)
        )
    return segments


def render_transcript_body(segments: Iterable[TranscriptSegment]) -> str:
    return "\n".join(
        f"[{_format_timestamp(segment.start_ms)}] {segment.text}"
        for segment in segments
    )


def render_transcript_markdown(document: TranscriptDocument) -> str:
    video = document.video
    track = document.track
    header = [
        f"# {video.get('title') or video.get('id')}",
        "",
        f"- URL: {video.get('url')}",
        f"- Channel: {video.get('channel') or 'Unknown'}",
        f"- Language: {track.get('language_name')} ({track.get('language_code')})",
        f"- Caption source: {track.get('source')}",
        f"- Retrieved: {document.retrieved_at}",
        "",
        "## Transcript",
        "",
    ]
    return "\n".join(header) + render_transcript_body(document.segments) + "\n"


def _json3_tracks(value: Any) -> Dict[str, Dict[str, Any]]:
    output: Dict[str, Dict[str, Any]] = {}
    if not isinstance(value, dict):
        return output
    for code, formats in value.items():
        if not isinstance(formats, list):
            continue
        selected = next(
            (
                item
                for item in formats
                if isinstance(item, dict)
                and item.get("ext") == "json3"
                and item.get("url")
            ),
            None,
        )
        if selected:
            output[str(code)] = selected
    return output


def _public_track(
    language_code: str, track: Dict[str, Any], source: str
) -> Dict[str, Any]:
    return {
        **track,
        "language_code": language_code,
        "language_name": track.get("name") or language_code,
        "source": source,
    }


def _match_language(requested: str, tracks: Dict[str, Any]) -> Optional[str]:
    normalized = requested.lower().replace("_", "-")
    exact = next(
        (code for code in tracks if code.lower().replace("_", "-") == normalized),
        None,
    )
    if exact:
        return exact
    requested_base = normalized.split("-", 1)[0]
    return next(
        (
            code
            for code in sorted(tracks)
            if code.lower().replace("_", "-").split("-", 1)[0] == requested_base
        ),
        None,
    )


def _normalize_requested_languages(languages: Optional[list[str]]) -> list[str]:
    output: list[str] = []
    for language in languages or []:
        normalized = str(language).strip().replace("_", "-")
        if normalized and normalized not in output:
            output.append(normalized)
    return output


def _format_timestamp(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds // 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _optional_int(value: Any) -> Optional[int]:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_slug(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "-", value).strip("-")[:32] or "unknown"
