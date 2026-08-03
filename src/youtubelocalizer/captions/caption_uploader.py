from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload

from .caption_client import CaptionClientError, list_caption_tracks
from .caption_downloader import CaptionSegment

logger = logging.getLogger(__name__)

_MEDIA_MIMETYPE = "application/octet-stream"

# Hard quota exhaustion — retrying immediately just burns more quota for
# certain failure; the caller should stop attempting further languages
# until the daily quota resets.
_QUOTA_EXHAUSTED_REASONS = {"quotaExceeded", "dailyLimitExceeded"}

# Transient — worth a few retries with backoff before giving up.
_RETRYABLE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "backendError", "internalError"}

_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 2.0


class CaptionUploadError(Exception):
    """Raised when converting to SRT or uploading a caption track fails."""


class CaptionQuotaExceededError(CaptionUploadError):
    """Raised when the API reports quota/daily-limit exhaustion.

    Deliberately not retried — the caller should stop attempting further
    languages this run rather than hitting the same wall repeatedly.
    """


def segments_to_srt(segments: List[CaptionSegment]) -> str:
    """Convert caption segments into valid SRT text. Pure formatting, no
    network calls."""
    blocks = []
    for index, seg in enumerate(segments, start=1):
        start_ts = _format_srt_timestamp(seg.start)
        end_ts = _format_srt_timestamp(seg.start + seg.duration)
        blocks.append(f"{index}\n{start_ts} --> {end_ts}\n{seg.text}")
    return "\n\n".join(blocks) + "\n"


def upload_caption(
    youtube: Resource,
    video_id: str,
    language_code: str,
    caption_segments: List[CaptionSegment],
    name: Optional[str] = None,
) -> str:
    """Create or update the caption track for `language_code` on `video_id`.

    Only ever touches the single caption track matching `language_code` —
    a different, separate API resource per track, so this cannot affect
    the Turkish source caption, other languages' manual captions, or
    metadata localizations (a completely different API endpoint).

    If a track already exists for `language_code`, its content is replaced
    (captions.update) rather than creating a duplicate; otherwise a new
    track is created (captions.insert). Returns the caption track's ID.

    Transient API errors are retried with exponential backoff. Quota/daily
    limit exhaustion raises CaptionQuotaExceededError immediately, without
    retrying — see that class's docstring for why.
    """
    if not caption_segments:
        raise CaptionUploadError("Cannot upload an empty list of caption segments.")

    srt_content = segments_to_srt(caption_segments)
    media = MediaInMemoryUpload(srt_content.encode("utf-8"), mimetype=_MEDIA_MIMETYPE, resumable=False)

    try:
        existing_tracks = list_caption_tracks(youtube, video_id)
    except CaptionClientError as exc:
        raise CaptionUploadError(f"Failed to check existing caption tracks: {exc}") from exc

    existing = next((t for t in existing_tracks if t.language_code == language_code), None)

    try:
        if existing is not None:
            response = _execute_with_retry(
                lambda: youtube.captions().update(
                    part="snippet",
                    body={
                        "id": existing.caption_id,
                        "snippet": {"language": language_code, "name": name or existing.name},
                    },
                    media_body=media,
                )
            )
            logger.info("Updated existing caption track '%s' (%s)", response["id"], language_code)
        else:
            response = _execute_with_retry(
                lambda: youtube.captions().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "videoId": video_id,
                            "language": language_code,
                            "name": name or "",
                            "isDraft": False,
                        }
                    },
                    media_body=media,
                )
            )
            logger.info("Created new caption track '%s' (%s)", response["id"], language_code)
    except CaptionQuotaExceededError:
        raise
    except HttpError as exc:
        raise CaptionUploadError(
            f"Failed to upload caption track for '{video_id}' ({language_code}): {exc}"
        ) from exc

    return response["id"]


def _execute_with_retry(request_factory: Callable[[], object]):
    """Call request_factory().execute(), retrying transient HttpErrors with
    exponential backoff. Quota/daily-limit errors raise
    CaptionQuotaExceededError immediately; other non-retryable errors
    propagate as HttpError for the caller to wrap.
    """
    last_exc: Optional[HttpError] = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            return request_factory().execute()
        except HttpError as exc:
            reason = _classify_http_error(exc)

            if reason in _QUOTA_EXHAUSTED_REASONS:
                raise CaptionQuotaExceededError(f"YouTube caption quota exceeded: {exc}") from exc

            if reason in _RETRYABLE_REASONS and attempt < _MAX_RETRIES:
                wait_seconds = _BACKOFF_BASE_SECONDS * (2**attempt)
                logger.warning(
                    "Transient caption API error (%s) — retrying in %.1fs (attempt %d/%d)",
                    reason,
                    wait_seconds,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                time.sleep(wait_seconds)
                last_exc = exc
                continue

            raise

    # Unreachable in practice (the loop always returns or raises), but
    # keeps type checkers happy and fails loudly instead of silently.
    raise last_exc  # type: ignore[misc]


def _classify_http_error(exc: HttpError) -> Optional[str]:
    """Extract the machine-readable error reason (e.g. "quotaExceeded")
    from an HttpError, if present."""
    details = getattr(exc, "error_details", None)
    if isinstance(details, list):
        for detail in details:
            if isinstance(detail, dict) and detail.get("reason"):
                return detail["reason"]
    return None


def _format_srt_timestamp(seconds: float) -> str:
    total_millis = round(seconds * 1000)
    hours, remainder = divmod(total_millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
