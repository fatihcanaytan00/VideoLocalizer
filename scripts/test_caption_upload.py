"""Standalone check for v0.2.0 Milestone 4: caption upload.

Downloads a video's Turkish ASR track, translates it into one language
(English), and uploads the result as that video's English caption track.
Not integrated into the orchestrator — this is a manual, one-language
verification tool only.

Does not touch metadata localization or caption translation logic; v0.1.1
behavior and the Milestone 3 translator are both untouched by this script.

Run with:
    python -m scripts.test_caption_upload --account ACCOUNT_NAME --video-id VIDEO_ID
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from youtubelocalizer.accounts import AccountsError, get_account, load_accounts
from youtubelocalizer.auth import AuthError, get_authenticated_service
from youtubelocalizer.captions.caption_client import CaptionClientError, list_caption_tracks
from youtubelocalizer.captions.caption_downloader import CaptionDownloadError, download_caption
from youtubelocalizer.captions.caption_translator import translate_caption_segments
from youtubelocalizer.captions.caption_uploader import CaptionUploadError, upload_caption
from youtubelocalizer.language_map import LanguageMapError, get_provider_code
from youtubelocalizer.translator import TranslationError, get_translator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SOURCE_LANGUAGE = "tr"
TARGET_LANGUAGE = "en"
VERIFY_TIMEOUT_S = 20
VERIFY_INTERVAL_S = 2


def _wait_for_track(youtube, video_id: str, caption_id: str):
    """Poll list_caption_tracks — YouTube's caption list can lag briefly
    after a write, same read-after-write delay observed for metadata
    localizations back in Milestone 5."""
    deadline = time.time() + VERIFY_TIMEOUT_S
    tracks = []
    while time.time() < deadline:
        tracks = list_caption_tracks(youtube, video_id)
        if any(t.caption_id == caption_id for t in tracks):
            return tracks
        time.sleep(VERIFY_INTERVAL_S)
    return tracks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload a translated English caption track to a video.")
    parser.add_argument("--account", required=True, help="Account profile name from config/accounts.yaml")
    parser.add_argument("--video-id", required=True, help="YouTube video ID to caption")
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

    print("--- Before ---")
    try:
        before_tracks = list_caption_tracks(youtube, args.video_id)
    except CaptionClientError as exc:
        logger.error("Failed to list caption tracks: %s", exc)
        return 1
    for t in before_tracks:
        print(f"  language={t.language_code} kind={t.track_kind} id={t.caption_id}")
    if not any(t.language_code == TARGET_LANGUAGE for t in before_tracks):
        print(f"  (no existing '{TARGET_LANGUAGE}' track — this run will INSERT a new one)")

    asr_tr_track = next((t for t in before_tracks if t.language_code == "tr" and t.track_kind == "asr"), None)
    if asr_tr_track is None:
        logger.error("No Turkish ASR caption track found for video '%s'.", args.video_id)
        return 1

    try:
        segments = download_caption(youtube, asr_tr_track.caption_id)
    except CaptionDownloadError as exc:
        logger.error("Failed to download caption track: %s", exc)
        return 1

    if not segments:
        logger.error("Turkish ASR caption track is empty — nothing to translate/upload.")
        return 1

    try:
        translator = get_translator("deep_translator_google")
        source_code = get_provider_code(SOURCE_LANGUAGE)
        target_code = get_provider_code(TARGET_LANGUAGE)
    except (TranslationError, LanguageMapError) as exc:
        logger.error("Translator setup error: %s", exc)
        return 1

    translated_segments = translate_caption_segments(segments, translator, source_code, target_code)
    print(f"\nTranslated {len(translated_segments)} segments ({SOURCE_LANGUAGE} -> {TARGET_LANGUAGE}).")

    try:
        caption_id = upload_caption(
            youtube,
            args.video_id,
            TARGET_LANGUAGE,
            translated_segments,
            name="English (auto-translated)",
        )
    except CaptionUploadError as exc:
        logger.error("Failed to upload caption track: %s", exc)
        return 1

    print(f"\nUpload complete. Caption track id: {caption_id}")

    print("\n--- After ---")
    try:
        after_tracks = _wait_for_track(youtube, args.video_id, caption_id)
    except CaptionClientError as exc:
        logger.error("Failed to list caption tracks after upload: %s", exc)
        return 1
    for t in after_tracks:
        print(f"  language={t.language_code} kind={t.track_kind} id={t.caption_id}")

    found = any(t.caption_id == caption_id and t.language_code == TARGET_LANGUAGE for t in after_tracks)
    print(f"\nVerification: '{TARGET_LANGUAGE}' track with id={caption_id} present: {found}")

    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
