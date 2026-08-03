from __future__ import annotations

import logging

from deep_translator import GoogleTranslator
from deep_translator.exceptions import BaseError, RequestError, ServerException, TooManyRequests

from .base import TranslationError, TranslatorProvider

logger = logging.getLogger(__name__)

# deep-translator's exception hierarchy isn't rooted at a single base class
# for every failure mode, so we catch this explicit set.
_PROVIDER_ERRORS = (BaseError, RequestError, ServerException, TooManyRequests)


class GoogleTranslateProvider(TranslatorProvider):
    """Translates text using deep-translator's Google Translate backend."""

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        if not text.strip():
            return text

        try:
            translator = GoogleTranslator(source=source_language, target=target_language)
            result = translator.translate(text)
        except _PROVIDER_ERRORS as exc:
            raise TranslationError(
                f"Translation failed ({source_language} -> {target_language}): {exc}"
            ) from exc

        if not result:
            raise TranslationError(
                f"Translation returned no result ({source_language} -> {target_language})"
            )
        return result
