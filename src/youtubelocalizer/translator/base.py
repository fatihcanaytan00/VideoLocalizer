from __future__ import annotations

from abc import ABC, abstractmethod


class TranslationError(Exception):
    """Raised when a translation request fails."""


class TranslatorProvider(ABC):
    """Abstract translation backend.

    Language codes passed here are provider-facing codes (see
    language_map.py for the mapping from this project's canonical codes),
    not YouTube's BCP-47 localization codes.
    """

    @abstractmethod
    def translate(self, text: str, source_language: str, target_language: str) -> str:
        raise NotImplementedError
