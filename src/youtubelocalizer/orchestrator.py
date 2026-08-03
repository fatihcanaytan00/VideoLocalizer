from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from googleapiclient.discovery import Resource

from .captions.caption_client import CaptionClientError, list_caption_tracks
from .captions.caption_downloader import CaptionDownloadError, download_caption
from .captions.caption_progress import (
    STATUS_FAILED,
    STATUS_QUOTA_EXCEEDED,
    STATUS_SUCCESS,
    CaptionProgressError,
    CaptionProgressStore,
)
from .captions.caption_translator import translate_caption_segments
from .captions.caption_uploader import CaptionQuotaExceededError, CaptionUploadError, upload_caption
from .config import Config
from .language_map import (
    LanguageMapError,
    get_display_name,
    get_provider_code,
    get_youtube_code,
    normalize_english_localization,
)
from .text_protection import protect_terms, restore_terms
from .translation_quality import check_translation_quality
from .translator import TranslationError, TranslatorProvider
from .youtube_client import (
    Localizations,
    VideoMetadata,
    YouTubeClientError,
    get_existing_localizations,
    get_latest_video,
    get_video_by_id,
    merge_localizations,
    update_localizations,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LanguageResult:
    canonical_code: str
    display_name: str
    success: bool
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


# Reporting-only states for CaptionLanguageResult. "success"/"failed"/
# "quota_exceeded" mirror caption_progress's persisted statuses;
# "skipped_existing" and "not_attempted" only ever describe this run's
# display and are never written to the state file.
STATUS_SKIPPED_EXISTING = "skipped_existing"
STATUS_NOT_ATTEMPTED = "not_attempted"


@dataclass(frozen=True)
class CaptionLanguageResult:
    canonical_code: str
    display_name: str
    success: bool
    status: str
    error: Optional[str] = None


@dataclass(frozen=True)
class CaptionRunResult:
    attempted: bool
    skip_reason: Optional[str] = None
    language_results: List[CaptionLanguageResult] = field(default_factory=list)

    @property
    def succeeded(self) -> List[CaptionLanguageResult]:
        return [r for r in self.language_results if r.success]

    @property
    def failed(self) -> List[CaptionLanguageResult]:
        return [r for r in self.language_results if not r.success]


@dataclass(frozen=True)
class RunResult:
    video: VideoMetadata
    language_results: List[LanguageResult]
    caption_result: CaptionRunResult

    @property
    def succeeded(self) -> List[LanguageResult]:
        return [r for r in self.language_results if r.success]

    @property
    def failed(self) -> List[LanguageResult]:
        return [r for r in self.language_results if not r.success]


def run_localization(
    youtube: Resource,
    config: Config,
    translator: TranslatorProvider,
    account_name: str,
    video_id: Optional[str] = None,
) -> RunResult:
    """Full workflow: select video -> translate metadata -> merge -> write
    -> (if metadata succeeded) translate + upload captions.

    If video_id is given, that specific video is localized; otherwise the
    channel's latest upload is used. Each target language is translated
    independently for metadata, so one language failing doesn't stop the
    others. All successful metadata translations are written to YouTube in
    a single batched update (one API call) rather than one write per
    language.

    Caption localization runs only after the metadata step completes (not
    only when every language succeeds — see below) and is fully isolated:
    a caption failure, or the entire caption step being skipped (no source
    ASR track), never affects the metadata result already computed.
    """
    video = get_video_by_id(youtube, video_id) if video_id else get_latest_video(youtube)
    logger.info("Localizing video '%s' (%s)", video.title, video.video_id)

    existing = get_existing_localizations(youtube, video.video_id)
    existing = normalize_english_localization(existing, config.english_localization_key)
    source_provider_code = get_provider_code(config.source_language)

    # Protecting is source-text-dependent only, so it happens once per run,
    # not once per language.
    protected_title, title_placeholders = protect_terms(video.title, config.protected_terms)
    protected_description, description_placeholders = protect_terms(
        video.description, config.protected_terms
    )

    new_localizations: Localizations = {}
    results: List[LanguageResult] = []

    for canonical_target in config.target_languages:
        display_name = get_display_name(canonical_target)
        try:
            target_provider_code = get_provider_code(canonical_target)
            youtube_code = (
                config.english_localization_key
                if canonical_target == "en"
                else get_youtube_code(canonical_target)
            )

            raw_title = translator.translate(protected_title, source_provider_code, target_provider_code)
            title = restore_terms(raw_title, title_placeholders)

            raw_description = translator.translate(
                protected_description, source_provider_code, target_provider_code
            )
            description = restore_terms(raw_description, description_placeholders)

            warnings = check_translation_quality(video.title, title) + check_translation_quality(
                video.description, description
            )

            new_localizations[youtube_code] = {"title": title, "description": description}
            results.append(LanguageResult(canonical_target, display_name, success=True, warnings=warnings))

            if warnings:
                logger.warning("%-12s SUCCESS (warnings: %s)", display_name, "; ".join(warnings))
            else:
                logger.info("%-12s SUCCESS", display_name)
        except (LanguageMapError, TranslationError) as exc:
            results.append(LanguageResult(canonical_target, display_name, success=False, error=str(exc)))
            logger.error("%-12s FAILED (%s)", display_name, exc)

    metadata_written = bool(new_localizations)
    if not metadata_written:
        logger.warning("No languages translated successfully — skipping YouTube update.")
    else:
        merged = merge_localizations(existing, new_localizations)
        try:
            update_localizations(youtube, video.video_id, merged)
        except YouTubeClientError as exc:
            # The write is one atomic call — if it failed, nothing from this
            # run was actually persisted, regardless of translation success.
            logger.error("Failed to write localizations to YouTube: %s", exc)
            metadata_written = False
            results = [
                LanguageResult(r.canonical_code, r.display_name, success=False, error=str(exc))
                for r in results
            ]

    if metadata_written:
        caption_result = _run_caption_pipeline(youtube, video, config, translator, account_name)
    else:
        reason = "Metadata localization did not succeed; captions were not attempted."
        logger.info("Captions: skipped (%s)", reason)
        caption_result = CaptionRunResult(attempted=False, skip_reason=reason)

    return RunResult(video=video, language_results=results, caption_result=caption_result)


def _run_caption_pipeline(
    youtube: Resource,
    video: VideoMetadata,
    config: Config,
    translator: TranslatorProvider,
    account_name: str,
) -> CaptionRunResult:
    """Translate and upload caption tracks from the source-language ASR
    track into every configured target language. Entirely isolated from
    the metadata result: any failure here — including finding no source
    track at all — is recorded on this result only and never raised.

    Resumable: languages already recorded as successfully uploaded (in a
    prior run on this same video/account) are skipped outright rather than
    re-uploaded — real testing showed caption uploads are quota-expensive,
    so re-doing unchanged work is wasteful, not just redundant. Once a
    quota-exhaustion error is hit, every remaining language is marked
    "not attempted" without making further API calls, rather than hitting
    the same wall repeatedly.
    """
    try:
        tracks = list_caption_tracks(youtube, video.video_id)
    except CaptionClientError as exc:
        logger.info("Captions: skipped (failed to list caption tracks: %s)", exc)
        return CaptionRunResult(attempted=False, skip_reason=str(exc))

    source_track = next(
        (t for t in tracks if t.language_code == config.source_language and t.track_kind == "asr"),
        None,
    )
    if source_track is None:
        reason = f"No '{config.source_language}' ASR caption track found."
        logger.info("Captions: skipped (%s)", reason)
        return CaptionRunResult(attempted=False, skip_reason=reason)

    try:
        segments = download_caption(youtube, source_track.caption_id)
    except CaptionDownloadError as exc:
        logger.info("Captions: skipped (failed to download source caption track: %s)", exc)
        return CaptionRunResult(attempted=False, skip_reason=str(exc))

    if not segments:
        reason = "Source caption track is empty."
        logger.info("Captions: skipped (%s)", reason)
        return CaptionRunResult(attempted=False, skip_reason=reason)

    progress_store = CaptionProgressStore(Path(config.captions.state_file))

    source_provider_code = get_provider_code(config.source_language)
    language_results: List[CaptionLanguageResult] = []
    quota_exhausted = False

    for canonical_target in config.target_languages:
        display_name = get_display_name(canonical_target)

        if quota_exhausted:
            language_results.append(
                CaptionLanguageResult(
                    canonical_target,
                    display_name,
                    success=False,
                    status=STATUS_NOT_ATTEMPTED,
                    error="Quota exhausted earlier in this run; not attempted.",
                )
            )
            logger.info("Captions: %-12s NOT ATTEMPTED (quota exhausted earlier this run)", display_name)
            continue

        try:
            prior_status = progress_store.get_status(account_name, video.video_id, canonical_target)
        except CaptionProgressError as exc:
            logger.warning("Caption progress store unavailable (%s); proceeding without it.", exc)
            prior_status = None

        if prior_status == STATUS_SUCCESS:
            language_results.append(
                CaptionLanguageResult(
                    canonical_target, display_name, success=True, status=STATUS_SKIPPED_EXISTING
                )
            )
            logger.info("Captions: %-12s SKIPPED (already uploaded in a previous run)", display_name)
            continue

        try:
            target_provider_code = get_provider_code(canonical_target)
            caption_language_code = get_youtube_code(canonical_target)

            translated_segments = translate_caption_segments(
                segments, translator, source_provider_code, target_provider_code
            )
            upload_caption(youtube, video.video_id, caption_language_code, translated_segments)

            language_results.append(
                CaptionLanguageResult(canonical_target, display_name, success=True, status=STATUS_SUCCESS)
            )
            logger.info("Captions: %-12s SUCCESS", display_name)
            _record_progress(progress_store, account_name, video.video_id, canonical_target, STATUS_SUCCESS)
        except CaptionQuotaExceededError as exc:
            language_results.append(
                CaptionLanguageResult(
                    canonical_target, display_name, success=False, status=STATUS_QUOTA_EXCEEDED, error=str(exc)
                )
            )
            logger.error("Captions: %-12s FAILED - quota exceeded", display_name)
            _record_progress(
                progress_store, account_name, video.video_id, canonical_target, STATUS_QUOTA_EXCEEDED
            )
            quota_exhausted = True
        except (LanguageMapError, TranslationError, CaptionUploadError) as exc:
            language_results.append(
                CaptionLanguageResult(
                    canonical_target, display_name, success=False, status=STATUS_FAILED, error=str(exc)
                )
            )
            logger.error("Captions: %-12s FAILED (%s)", display_name, exc)
            _record_progress(progress_store, account_name, video.video_id, canonical_target, STATUS_FAILED)

    return CaptionRunResult(attempted=True, language_results=language_results)


def _record_progress(
    store: CaptionProgressStore, account_name: str, video_id: str, canonical_target: str, status: str
) -> None:
    try:
        store.record(account_name, video_id, canonical_target, status)
    except CaptionProgressError as exc:
        logger.warning("Failed to persist caption progress for '%s': %s", canonical_target, exc)
