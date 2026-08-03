from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


class LanguageMapError(Exception):
    """Raised when a canonical language code has no known mapping."""


@dataclass(frozen=True)
class LanguageCodes:
    provider_code: str  # code the translation provider (deep-translator) expects
    youtube_code: str  # BCP-47 code YouTube's `localizations` field expects
    display_name: str  # human-readable name, used in logs/summaries only


# Canonical codes are what config.yaml / this project use everywhere else.
# For most languages the provider code and the YouTube code are identical;
# where that's genuinely uncertain (regional variants), it's called out
# below rather than guessed.
#
# English's youtube_code here is only a fallback default. The actual key
# written is config.english_localization_key (default "en") — see
# normalize_english_localization() below, which standardizes existing
# "en"/"en-US" entries to that key before any write happens.
_LANGUAGE_MAP: Dict[str, LanguageCodes] = {
    "tr": LanguageCodes("tr", "tr", "Turkish"),  # source
    "de": LanguageCodes("de", "de", "German"),
    "ar": LanguageCodes("ar", "ar", "Arabic"),
    "az": LanguageCodes("az", "az", "Azerbaijani"),
    "bg": LanguageCodes("bg", "bg", "Bulgarian"),
    "id": LanguageCodes("id", "id", "Indonesian"),
    "fa": LanguageCodes("fa", "fa", "Persian"),
    "fr": LanguageCodes("fr", "fr", "French"),
    "hi": LanguageCodes("hi", "hi", "Hindi"),
    "ja": LanguageCodes("ja", "ja", "Japanese"),
    "ko": LanguageCodes("ko", "ko", "Korean"),
    "pt": LanguageCodes("pt", "pt", "Portuguese"),  # YouTube may require pt-BR/pt-PT; unverified
    "ru": LanguageCodes("ru", "ru", "Russian"),
    "uk": LanguageCodes("uk", "uk", "Ukrainian"),
    "vi": LanguageCodes("vi", "vi", "Vietnamese"),
    "el": LanguageCodes("el", "el", "Greek"),
    "zh-CN": LanguageCodes("zh-CN", "zh-CN", "Chinese"),
    "en": LanguageCodes("en", "en", "English"),  # actual key: config.english_localization_key
    "es": LanguageCodes("es", "es", "Spanish"),
    "sv": LanguageCodes("sv", "sv", "Swedish"),
    "it": LanguageCodes("it", "it", "Italian"),
}


def get_provider_code(canonical_code: str) -> str:
    return _lookup(canonical_code).provider_code


def get_youtube_code(canonical_code: str) -> str:
    return _lookup(canonical_code).youtube_code


# Real-world English localization keys seen on YouTube. Some videos use
# "en", others "en-US" (confirmed via real accounts in v0.1.0 testing).
# v0.1.1 standardizes to a single configurable key instead of just picking
# whichever already exists.
_ENGLISH_KEY_VARIANTS: List[str] = ["en", "en-US"]


def normalize_english_localization(
    existing: Dict[str, Dict[str, str]], preferred_key: str
) -> Dict[str, Dict[str, str]]:
    """Collapse existing English localization key(s) down to `preferred_key`.

    - If a non-preferred English variant exists (e.g. "en-US" when
      preferred is "en") and `preferred_key` has no content yet, the
      variant's content is moved to `preferred_key`.
    - If `preferred_key` already has content, the non-preferred variant is
      simply dropped as a stray duplicate (preferred_key's content is left
      for the caller to update normally).
    - Every other (non-English) entry is returned untouched.

    Returns a new dict; does not mutate `existing`. No-op if
    `preferred_key` isn't one of the known English variants.
    """
    if preferred_key not in _ENGLISH_KEY_VARIANTS:
        return dict(existing)

    normalized = dict(existing)
    for other_key in _ENGLISH_KEY_VARIANTS:
        if other_key == preferred_key:
            continue
        other_content = normalized.pop(other_key, None)
        if other_content is not None and preferred_key not in normalized:
            normalized[preferred_key] = other_content

    return normalized


def get_display_name(canonical_code: str) -> str:
    return _lookup(canonical_code).display_name


def _lookup(canonical_code: str) -> LanguageCodes:
    try:
        return _LANGUAGE_MAP[canonical_code]
    except KeyError as exc:
        raise LanguageMapError(
            f"No language mapping defined for code '{canonical_code}'. "
            f"Known codes: {sorted(_LANGUAGE_MAP)}"
        ) from exc
