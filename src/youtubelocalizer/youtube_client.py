from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 50

# language_code (YouTube BCP-47) -> {"title": ..., "description": ...}
Localizations = Dict[str, Dict[str, str]]


class YouTubeClientError(Exception):
    """Raised when a YouTube Data API call fails or returns unexpected data."""


@dataclass(frozen=True)
class VideoMetadata:
    video_id: str
    title: str
    description: str
    published_at: str


@dataclass(frozen=True)
class VideoSummary:
    video_id: str
    title: str
    published_at: str


def get_uploads_playlist_id(youtube: Resource) -> str:
    try:
        response = youtube.channels().list(part="contentDetails", mine=True).execute()
    except HttpError as exc:
        raise YouTubeClientError(f"Failed to fetch channel details: {exc}") from exc

    items = response.get("items", [])
    if not items:
        raise YouTubeClientError("No channel found for the authenticated account.")

    try:
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except KeyError as exc:
        raise YouTubeClientError("Channel response did not include an uploads playlist.") from exc


def get_recent_videos(youtube: Resource, limit: int) -> List[VideoSummary]:
    """Return up to `limit` most recently uploaded videos, newest first."""
    if limit < 1:
        raise ValueError("limit must be at least 1")

    uploads_playlist_id = get_uploads_playlist_id(youtube)

    summaries: List[VideoSummary] = []
    page_token: Optional[str] = None

    while len(summaries) < limit:
        try:
            response = (
                youtube.playlistItems()
                .list(
                    part="snippet,contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=min(MAX_PAGE_SIZE, limit - len(summaries)),
                    pageToken=page_token,
                )
                .execute()
            )
        except HttpError as exc:
            raise YouTubeClientError(f"Failed to fetch uploads playlist items: {exc}") from exc

        items = response.get("items", [])
        if not items:
            break

        for item in items:
            try:
                video_id = item["contentDetails"]["videoId"]
            except KeyError as exc:
                raise YouTubeClientError("Playlist item did not include a video ID.") from exc

            snippet = item.get("snippet", {})
            # videoPublishedAt is the video's actual publish time; fall back
            # to the playlist item's own snippet.publishedAt if absent.
            published_at = item["contentDetails"].get("videoPublishedAt") or snippet.get(
                "publishedAt", ""
            )
            summaries.append(
                VideoSummary(video_id=video_id, title=snippet.get("title", ""), published_at=published_at)
            )

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return summaries[:limit]


def get_video_by_id(youtube: Resource, video_id: str) -> VideoMetadata:
    try:
        response = youtube.videos().list(part="snippet", id=video_id).execute()
    except HttpError as exc:
        raise YouTubeClientError(f"Failed to fetch video details for '{video_id}': {exc}") from exc

    items = response.get("items", [])
    if not items:
        raise YouTubeClientError(f"Video '{video_id}' not found.")

    snippet = items[0]["snippet"]
    return VideoMetadata(
        video_id=video_id,
        title=snippet.get("title", ""),
        description=snippet.get("description", ""),
        published_at=snippet.get("publishedAt", ""),
    )


def get_latest_video(youtube: Resource) -> VideoMetadata:
    """Convenience wrapper: the single most recent upload, full metadata."""
    recent = get_recent_videos(youtube, limit=1)
    if not recent:
        raise YouTubeClientError("Uploads playlist is empty — no videos found.")

    logger.info("Latest uploaded video ID: %s", recent[0].video_id)
    return get_video_by_id(youtube, recent[0].video_id)


def get_existing_localizations(youtube: Resource, video_id: str) -> Localizations:
    try:
        response = youtube.videos().list(part="localizations", id=video_id).execute()
    except HttpError as exc:
        raise YouTubeClientError(f"Failed to fetch localizations for '{video_id}': {exc}") from exc

    items = response.get("items", [])
    if not items:
        raise YouTubeClientError(f"Video '{video_id}' not found.")

    return items[0].get("localizations", {})


def merge_localizations(existing: Localizations, new: Localizations) -> Localizations:
    """Combine existing localizations with newly generated ones.

    Languages present in `new` overwrite the same language in `existing`;
    every other existing language is preserved untouched.
    """
    merged = dict(existing)
    merged.update(new)
    return merged


def update_localizations(youtube: Resource, video_id: str, localizations: Localizations) -> None:
    # part="localizations" with a body containing only id + localizations
    # (no "snippet" key) means the API updates *only* the localizations
    # field — snippet.title/snippet.description are left untouched.
    body = {"id": video_id, "localizations": localizations}
    try:
        youtube.videos().update(part="localizations", body=body).execute()
    except HttpError as exc:
        raise YouTubeClientError(f"Failed to update localizations for '{video_id}': {exc}") from exc
