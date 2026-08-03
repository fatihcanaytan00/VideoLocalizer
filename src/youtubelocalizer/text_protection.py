from __future__ import annotations

import re
from typing import Dict, List, Tuple

# Placeholder tokens have no spaces and no dictionary meaning, so machine
# translation backends tend to pass them through unchanged. Not guaranteed —
# always restore_terms() the output rather than assuming the token survived.
_PLACEHOLDER_TEMPLATE = "__PT{index}__"


def protect_terms(text: str, terms: List[str]) -> Tuple[str, Dict[str, str]]:
    """Replace each occurrence of a protected term with a placeholder token.

    Matching is case-insensitive — video titles are often ALL CAPS while a
    protected term is typically configured in natural casing (confirmed a
    real mismatch during testing: config "Fatih Can Aytan" vs. an actual
    title "FATİH CAN AYTAN"). The *source text's* casing is what gets
    restored, not the config's, so "FATİH CAN AYTAN" comes back exactly as
    it appeared, not silently re-cased to the config's version.

    Returns (protected_text, placeholder_map); pass placeholder_map to
    restore_terms() after translation to put the originals back.
    """
    protected_text = text
    placeholder_map: Dict[str, str] = {}

    for index, term in enumerate(terms):
        if not term:
            continue
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        match = pattern.search(protected_text)
        if not match:
            continue
        placeholder = _PLACEHOLDER_TEMPLATE.format(index=index)
        placeholder_map[placeholder] = match.group(0)
        protected_text = pattern.sub(placeholder, protected_text)

    return protected_text, placeholder_map


def restore_terms(text: str, placeholder_map: Dict[str, str]) -> str:
    restored = text
    for placeholder, term in placeholder_map.items():
        restored = restored.replace(placeholder, term)
    return restored
