from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Requesting this format explicitly means we always parse one known,
# well-understood text format, regardless of the track's original/native
# storage format (which can vary — ttml, scc, sbv, ...) — the API
# transcodes to whatever tfmt is requested.
_DOWNLOAD_FORMAT = "srt"

_SRT_TIMESTAMP_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")


class CaptionDownloadError(Exception):
    """Raised when downloading or parsing a caption track fails."""


@dataclass(frozen=True)
class CaptionSegment:
    start: float  # seconds
    duration: float  # seconds
    text: str


def download_caption(youtube: Resource, caption_id: str) -> List[CaptionSegment]:
    """Download and parse one caption track. Does not translate or upload.

    Returns an empty list for an empty/blank caption track rather than
    raising — that's valid data, not a failure.
    """
    try:
        request = youtube.captions().download(id=caption_id, tfmt=_DOWNLOAD_FORMAT)
        raw = request.execute()
    except HttpError as exc:
        raise CaptionDownloadError(f"Failed to download caption track '{caption_id}': {exc}") from exc

    content = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)

    if not content.strip():
        return []

    return _parse_srt(content)


def _parse_srt(content: str) -> List[CaptionSegment]:
    segments: List[CaptionSegment] = []

    for block in re.split(r"\r?\n\r?\n+", content.strip()):
        block = block.strip()
        if not block:
            continue

        lines = block.splitlines()
        time_line_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if time_line_index is None:
            continue  # not a well-formed cue block (e.g. a stray index line) — skip

        start_str, end_str = (part.strip() for part in lines[time_line_index].split("-->"))
        start = _parse_srt_timestamp(start_str)
        end = _parse_srt_timestamp(end_str)
        text = "\n".join(lines[time_line_index + 1 :]).strip()

        segments.append(CaptionSegment(start=start, duration=max(end - start, 0.0), text=text))

    return segments


def _parse_srt_timestamp(timestamp: str) -> float:
    match = _SRT_TIMESTAMP_RE.match(timestamp.strip())
    if not match:
        raise CaptionDownloadError(f"Unrecognized SRT timestamp: '{timestamp}'")
    hours, minutes, seconds, millis = (int(g) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000
