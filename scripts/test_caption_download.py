"""Standalone check for v0.2.0 Milestone 2: download and parse a caption track.

Finds the video's Turkish ASR (auto-generated) track via list_caption_tracks
(Milestone 1) and downloads it. Read-only — no translation, no upload.
Does not touch metadata localization, English normalization, protected
terms, or quality warnings; v0.1.1 behavior is untouched by this script.

Run with:
    python -m scripts.test_caption_download --account ACCOUNT_NAME --video-id VIDEO_ID
"""
from __future__ import annotations

import argparse
import logging
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from youtubelocalizer.accounts import AccountsError, get_account, load_accounts
from youtubelocalizer.auth import AuthError, get_authenticated_service
from youtubelocalizer.captions.caption_client import CaptionClientError, list_caption_tracks
from youtubelocalizer.captions.caption_downloader import CaptionDownloadError, download_caption

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and parse a video's Turkish ASR caption track.")
    parser.add_argument("--account", required=True, help="Account profile name from config/accounts.yaml")
    parser.add_argument("--video-id", required=True, help="YouTube video ID to inspect")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        profiles = load_accounts("config/accounts.yaml")
        account = get_account(profiles, args.account)
    except AccountsError as exc:
        logger.error("Accounts error: %s", exc)
        return 1

    try:
        youtube = get_authenticated_service(account)
    except AuthError as exc:
        logger.error("Authentication error for account '%s': %s", account.name, exc)
        return 1

    try:
        tracks = list_caption_tracks(youtube, args.video_id)
    except CaptionClientError as exc:
        logger.error("Failed to list caption tracks: %s", exc)
        return 1

    asr_tr_track = next((t for t in tracks if t.language_code == "tr" and t.track_kind == "asr"), None)
    if asr_tr_track is None:
        logger.error("No Turkish ASR caption track found for video '%s'.", args.video_id)
        return 1

    print(
        f"Using caption track: id={asr_tr_track.caption_id} "
        f"language={asr_tr_track.language_code} kind={asr_tr_track.track_kind}\n"
    )

    try:
        segments = download_caption(youtube, asr_tr_track.caption_id)
    except CaptionDownloadError as exc:
        logger.error("Failed to download caption track: %s", exc)
        return 1

    print(f"Segments: {len(segments)}")
    if not segments:
        print("(no caption segments — empty track)")
        return 0

    print("First 5 segments:")
    for seg in segments[:5]:
        print(f"  [start={seg.start:.2f}s duration={seg.duration:.2f}s] {seg.text}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
