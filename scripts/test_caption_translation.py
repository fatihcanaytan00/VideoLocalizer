"""Standalone check for v0.2.0 Milestone 3: caption translation.

Downloads a small sample of a video's real Turkish ASR track (Milestone 2)
and translates it into English and German using the existing
TranslatorProvider abstraction, batching requests rather than sending one
per segment. Does not upload anything to YouTube.

Does not touch metadata localization, English normalization, protected
terms, or quality warnings; v0.1.1 behavior is untouched by this script.

Run with:
    python -m scripts.test_caption_translation --account ACCOUNT_NAME --video-id VIDEO_ID
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
from youtubelocalizer.captions.caption_translator import translate_caption_segments
from youtubelocalizer.language_map import LanguageMapError, get_provider_code
from youtubelocalizer.translator import TranslationError, get_translator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SAMPLE_SIZE = 8
SOURCE_LANGUAGE = "tr"
TARGET_LANGUAGES = ["en", "de"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Translate a sample of a video's Turkish ASR captions.")
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

    try:
        segments = download_caption(youtube, asr_tr_track.caption_id)
    except CaptionDownloadError as exc:
        logger.error("Failed to download caption track: %s", exc)
        return 1

    if not segments:
        print("(caption track is empty — nothing to translate)")
        return 0

    sample = segments[:SAMPLE_SIZE]
    print(f"Translating a sample of {len(sample)} segments (of {len(segments)} total).\n")

    print("=== Before (source, tr) ===")
    for seg in sample:
        print(f"  [{seg.start:.2f}s +{seg.duration:.2f}s] {seg.text}")

    try:
        translator = get_translator("deep_translator_google")
        source_code = get_provider_code(SOURCE_LANGUAGE)
    except (TranslationError, LanguageMapError) as exc:
        logger.error("Translator setup error: %s", exc)
        return 1

    exit_code = 0
    for canonical_target in TARGET_LANGUAGES:
        try:
            target_code = get_provider_code(canonical_target)
        except LanguageMapError as exc:
            logger.error("Language map error for '%s': %s", canonical_target, exc)
            exit_code = 1
            continue

        translated = translate_caption_segments(sample, translator, source_code, target_code)

        print(f"\n=== After ({canonical_target}) ===")
        for original, result in zip(sample, translated):
            assert result.start == original.start, "start time must be preserved"
            assert result.duration == original.duration, "duration must be preserved"
            print(f"  [{result.start:.2f}s +{result.duration:.2f}s] {result.text}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
