from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class CaptionClientError(Exception):
    """Raised when a YouTube Captions API call fails or returns unexpected data."""


@dataclass(frozen=True)
class CaptionTrack:
    caption_id: str
    language_code: str
    name: str
    track_kind: str


def list_caption_tracks(youtube: Resource, video_id: str) -> List[CaptionTrack]:
    """Return the caption tracks available for `video_id`.

    Read-only: does not download, translate, or upload any caption content.
    """
    try:
        response = youtube.captions().list(part="snippet", videoId=video_id).execute()
    except HttpError as exc:
        raise CaptionClientError(f"Failed to fetch caption tracks for '{video_id}': {exc}") from exc

    items = response.get("items", [])
    tracks: List[CaptionTrack] = []

    for item in items:
        try:
            caption_id = item["id"]
            snippet = item["snippet"]
            tracks.append(
                CaptionTrack(
                    caption_id=caption_id,
                    language_code=snippet.get("language", ""),
                    name=snippet.get("name", ""),
                    track_kind=snippet.get("trackKind", ""),
                )
            )
        except KeyError as exc:
            raise CaptionClientError(f"Caption track response missing expected field: {exc}") from exc

    return tracks
