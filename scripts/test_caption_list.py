"""Standalone check for v0.2.0 Milestone 1: list a video's caption tracks.

Read-only — does not download, translate, or upload captions. Does not
touch metadata localization, English normalization, protected terms, or
quality warnings; v0.1.1 behavior is untouched by this script.

Run with:
    python -m scripts.test_caption_list --account ACCOUNT_NAME --video-id VIDEO_ID
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List caption tracks available for a video.")
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

    print(f"Video: {args.video_id}")
    print(f"Caption tracks found: {len(tracks)}")
    if not tracks:
        print("(none)")
        return 0

    for track in tracks:
        print(
            f"  - id={track.caption_id}  language={track.language_code}  "
            f"kind={track.track_kind}  name='{track.name}'"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
