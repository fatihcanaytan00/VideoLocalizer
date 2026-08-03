"""Control-flow verification for v0.2.0 Milestone 6 caption hardening.

Real YouTube API quota was fully exhausted during development (even
captions.list, 1 unit, started failing) before this logic could be
exercised against a live quota-exceeded response reaching the actual
upload call. This script verifies the orchestrator's *control flow* —
resumable skip, quota-triggered cutoff, not-attempted marking — using
mocked I/O boundary functions instead, since the real dependency (a live
quota-exhausted account) isn't available on demand. This is a
control-flow check, not a substitute for the live test in
scripts/test_caption_upload.py.

Scenario: 4 target languages [de, fr, en, es].
  - de, fr: already recorded as successfully uploaded in a prior run.
  - en: upload raises CaptionQuotaExceededError (simulated).
  - es: must be marked "not attempted" WITHOUT any upload call being made.

Run with:
    python -m scripts.test_caption_hardening
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from youtubelocalizer.captions.caption_client import CaptionTrack
from youtubelocalizer.captions.caption_downloader import CaptionSegment
from youtubelocalizer.captions.caption_progress import STATUS_SUCCESS, CaptionProgressStore
from youtubelocalizer.captions.caption_uploader import CaptionQuotaExceededError
from youtubelocalizer.config import CaptionsConfig, Config, LoggingConfig, TranslationConfig
from youtubelocalizer.orchestrator import (
    STATUS_NOT_ATTEMPTED,
    STATUS_QUOTA_EXCEEDED,
    STATUS_SKIPPED_EXISTING,
    _run_caption_pipeline,
)
from youtubelocalizer.translator.base import TranslatorProvider
from youtubelocalizer.youtube_client import VideoMetadata

ACCOUNT = "test_account"
VIDEO_ID = "test_video"


class FakeTranslator(TranslatorProvider):
    def translate(self, text: str, source_language: str, target_language: str) -> str:
        return f"[{target_language}] {text}"


def main() -> int:
    state_path = Path("scratch_hardening_state.json")
    if state_path.exists():
        state_path.unlink()

    config = Config(
        source_language="tr",
        target_languages=["de", "fr", "en", "es"],
        translation=TranslationConfig(provider="deep_translator_google"),
        logging=LoggingConfig(directory="logs", level="INFO"),
        protected_terms=[],
        english_localization_key="en",
        captions=CaptionsConfig(state_file=str(state_path)),
    )

    # Seed de/fr as already successfully uploaded in a "previous run".
    store = CaptionProgressStore(state_path)
    store.record(ACCOUNT, VIDEO_ID, "de", STATUS_SUCCESS)
    store.record(ACCOUNT, VIDEO_ID, "fr", STATUS_SUCCESS)

    video = VideoMetadata(video_id=VIDEO_ID, title="Test", description="Bir zamanlar bir test vardı.", published_at="")
    fake_source_track = CaptionTrack(caption_id="src123", language_code="tr", name="", track_kind="asr")
    fake_segments = [CaptionSegment(start=0.0, duration=2.0, text="Bir zamanlar bir test vardı.")]

    upload_calls = []

    def fake_upload_caption(youtube, video_id, language_code, segments, name=None):
        upload_calls.append(language_code)
        if language_code == "en":
            raise CaptionQuotaExceededError("simulated quota exhaustion")
        return "fake_caption_id"

    with patch(
        "youtubelocalizer.orchestrator.list_caption_tracks", return_value=[fake_source_track]
    ), patch(
        "youtubelocalizer.orchestrator.download_caption", return_value=fake_segments
    ), patch(
        "youtubelocalizer.orchestrator.upload_caption", side_effect=fake_upload_caption
    ):
        result = _run_caption_pipeline(youtube=None, video=video, config=config, translator=FakeTranslator(), account_name=ACCOUNT)

    print(f"attempted: {result.attempted}")
    for r in result.language_results:
        print(f"  {r.canonical_code}: status={r.status} success={r.success}")

    statuses = {r.canonical_code: r.status for r in result.language_results}

    assert statuses["de"] == STATUS_SKIPPED_EXISTING, f"de should be skipped_existing, got {statuses['de']}"
    assert statuses["fr"] == STATUS_SKIPPED_EXISTING, f"fr should be skipped_existing, got {statuses['fr']}"
    assert statuses["en"] == STATUS_QUOTA_EXCEEDED, f"en should be quota_exceeded, got {statuses['en']}"
    assert statuses["es"] == STATUS_NOT_ATTEMPTED, f"es should be not_attempted, got {statuses['es']}"

    assert "de" not in upload_calls, "de was already successful — upload_caption must not be called for it"
    assert "fr" not in upload_calls, "fr was already successful — upload_caption must not be called for it"
    assert "en" in upload_calls, "en should have been attempted"
    assert "es" not in upload_calls, "es must NOT be attempted after quota exhaustion on en"

    # Verify persisted state: de/fr keep their original success record,
    # en is now recorded as quota_exceeded, es is untouched (never attempted).
    assert store.get_status(ACCOUNT, VIDEO_ID, "de") == STATUS_SUCCESS
    assert store.get_status(ACCOUNT, VIDEO_ID, "fr") == STATUS_SUCCESS
    assert store.get_status(ACCOUNT, VIDEO_ID, "en") == STATUS_QUOTA_EXCEEDED
    assert store.get_status(ACCOUNT, VIDEO_ID, "es") is None

    print("\nAll control-flow assertions passed:")
    print("  - already-successful languages (de, fr) skipped without an upload call")
    print("  - quota exhaustion on 'en' correctly classified and recorded")
    print("  - 'es' marked not_attempted with zero upload calls after the quota hit")
    print("  - state file correctly reflects all four outcomes")

    state_path.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
