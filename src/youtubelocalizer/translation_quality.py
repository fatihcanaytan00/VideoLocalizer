from __future__ import annotations

import difflib
from typing import List

# Below this length, comparing similarity ratios is noisy (short strings,
# e.g. "IMG 4388", are often legitimately identical across languages).
_MIN_LENGTH_FOR_SIMILARITY_CHECK = 20
_SUSPICIOUS_SIMILARITY_RATIO = 0.9


def check_translation_quality(source: str, translated: str) -> List[str]:
    """Lightweight, non-LLM heuristic checks on one translated field.

    Returns a list of human-readable warning strings (empty if nothing
    looks off). These are warnings, not errors — a genuinely identical
    translation can be correct (numbers, URLs, protected terms).
    """
    warnings: List[str] = []

    translated_stripped = translated.strip()
    if not translated_stripped:
        warnings.append("empty output")
        return warnings

    source_stripped = source.strip()
    if not source_stripped:
        return warnings

    if source_stripped == translated_stripped:
        warnings.append("identical to source")
    elif _is_suspiciously_unchanged(source_stripped, translated_stripped):
        warnings.append("suspiciously unchanged text")

    return warnings


def _is_suspiciously_unchanged(source: str, translated: str) -> bool:
    if len(source) < _MIN_LENGTH_FOR_SIMILARITY_CHECK:
        return False
    ratio = difflib.SequenceMatcher(None, source, translated).ratio()
    return ratio >= _SUSPICIOUS_SIMILARITY_RATIO
