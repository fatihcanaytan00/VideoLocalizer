"""One-off, manual validation of the YouTube localization write path.

Writes REAL localizations to a REAL video on the given account. This is a
manual verification tool, not part of the production CLI — full run
orchestration (pick video -> translate -> write) is implemented in M6.

Targets [de] then [fr] specifically because this video already has real
pre-existing localizations (tr, en-US) — using different languages proves
the merge preserves untouched pre-existing entries without touching them.

Runs two phases against the same video to prove merge behavior, not just
assume it:
  Phase 1: write [de]. Verify tr/en-US (pre-existing) are untouched.
  Phase 2: write [fr] only. Verify de (Phase 1) AND tr/en-US survive.

Also verifies snippet.title / snippet.description (the default Turkish
metadata) are unchanged after both writes.

YouTube's localizations read can lag briefly after a write (observed during
development), so read-back polls with a short retry instead of asserting
immediately.

Run with:
    python -m scripts.test_localization_write
"""
from __future__ import annotations

import logging
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from youtubelocalizer.accounts import get_account, load_accounts
from youtubelocalizer.auth import get_authenticated_service
from youtubelocalizer.config import load_config
from youtubelocalizer.language_map import get_provider_code, get_youtube_code
from youtubelocalizer.translator import get_translator
from youtubelocalizer.youtube_client import (
    Localizations,
    get_existing_localizations,
    get_video_by_id,
    merge_localizations,
    update_localizations,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ACCOUNT_NAME = "account_1"
VIDEO_ID = "6MnUlJLmObI"
READBACK_TIMEOUT_S = 20
READBACK_INTERVAL_S = 2


def build_payload(translator, source_lang: str, video, canonical_targets) -> Localizations:
    source_code = get_provider_code(source_lang)
    payload: Localizations = {}
    for canonical in canonical_targets:
        target_code = get_provider_code(canonical)
        youtube_code = get_youtube_code(canonical)
        title = translator.translate(video.title, source_code, target_code)
        description = translator.translate(video.description, source_code, target_code)
        payload[youtube_code] = {"title": title, "description": description}
    return payload


def print_payload(payload: Localizations) -> None:
    for lang, fields in payload.items():
        print(f"  [{lang}] title: {fields['title']}")
        print(f"  [{lang}] description: {fields['description'][:100]}...")


def wait_for_keys(youtube, video_id: str, expected_keys) -> Localizations:
    """Poll get_existing_localizations until expected_keys are present or timeout."""
    deadline = time.time() + READBACK_TIMEOUT_S
    latest: Localizations = {}
    while time.time() < deadline:
        latest = get_existing_localizations(youtube, video_id)
        if expected_keys <= set(latest.keys()):
            return latest
        time.sleep(READBACK_INTERVAL_S)
    return latest


def main() -> int:
    config = load_config("config/config.yaml")
    profiles = load_accounts("config/accounts.yaml")
    account = get_account(profiles, ACCOUNT_NAME)
    youtube = get_authenticated_service(account)
    translator = get_translator(config.translation.provider)

    video = get_video_by_id(youtube, VIDEO_ID)
    print(f"Target video: {video.video_id}")
    print(f"Original title (tr): {video.title}")
    print(f"Original description length: {len(video.description)} chars\n")

    baseline = get_existing_localizations(youtube, VIDEO_ID)
    print(f"Pre-existing localizations (untouched by this test): {list(baseline.keys())}\n")

    # --- Phase 1: write [de] ---
    print("=== Phase 1: writing [de] ===")
    new_1 = build_payload(translator, config.source_language, video, ["de"])
    print("Generated payload (Phase 1):")
    print_payload(new_1)

    merged_1 = merge_localizations(baseline, new_1)
    update_localizations(youtube, VIDEO_ID, merged_1)
    print("Write sent.\n")

    readback_1 = wait_for_keys(youtube, VIDEO_ID, set(new_1.keys()))
    print(f"Read-back after Phase 1: {list(readback_1.keys())}")
    for lang, fields in new_1.items():
        assert lang in readback_1, f"{lang} missing after Phase 1 write"
        assert readback_1[lang]["title"] == fields["title"], f"{lang} title mismatch after write"
        assert readback_1[lang]["description"] == fields["description"], f"{lang} description mismatch"
    for lang, fields in baseline.items():
        assert readback_1.get(lang) == fields, f"pre-existing '{lang}' changed during Phase 1!"
    print("Phase 1 verified OK: de added, tr/en-US untouched.\n")

    # --- Phase 2: write [fr] only, confirm de + baseline preserved by the merge ---
    print("=== Phase 2: writing [fr], verifying merge preserves de + baseline ===")
    new_2 = build_payload(translator, config.source_language, video, ["fr"])
    print("Generated payload (Phase 2):")
    print_payload(new_2)

    merged_2 = merge_localizations(readback_1, new_2)
    update_localizations(youtube, VIDEO_ID, merged_2)
    print("Write sent.\n")

    readback_2 = wait_for_keys(youtube, VIDEO_ID, set(new_2.keys()))
    print(f"Read-back after Phase 2: {list(readback_2.keys())}")
    for lang, fields in new_2.items():
        assert lang in readback_2, f"{lang} missing after Phase 2 write"
        assert readback_2[lang]["title"] == fields["title"], f"{lang} title mismatch after write"
    for lang, fields in new_1.items():
        assert readback_2.get(lang) == fields, f"'{lang}' (Phase 1) was lost/changed during Phase 2!"
    for lang, fields in baseline.items():
        assert readback_2.get(lang) == fields, f"pre-existing '{lang}' changed during Phase 2!"
    print("Phase 2 verified OK: fr added, de (Phase 1) and tr/en-US (pre-existing) all unchanged.\n")

    # --- Confirm the default (Turkish) snippet was never touched ---
    video_after = get_video_by_id(youtube, VIDEO_ID)
    assert video_after.title == video.title, "snippet.title was modified!"
    assert video_after.description == video.description, "snippet.description was modified!"
    print("Confirmed: snippet.title and snippet.description (Turkish default) are unchanged.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
