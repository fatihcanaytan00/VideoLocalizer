from __future__ import annotations

from typing import Dict, Type

from .base import TranslationError, TranslatorProvider
from .google_translate import GoogleTranslateProvider

# Keys here must match config.yaml's translation.provider values
# (see SUPPORTED_TRANSLATION_PROVIDERS in config.py).
_PROVIDERS: Dict[str, Type[TranslatorProvider]] = {
    "deep_translator_google": GoogleTranslateProvider,
}


def get_translator(provider_name: str) -> TranslatorProvider:
    try:
        provider_cls = _PROVIDERS[provider_name]
    except KeyError as exc:
        raise TranslationError(
            f"Unknown translation provider '{provider_name}'. Available: {sorted(_PROVIDERS)}"
        ) from exc
    return provider_cls()


__all__ = ["TranslationError", "TranslatorProvider", "GoogleTranslateProvider", "get_translator"]
