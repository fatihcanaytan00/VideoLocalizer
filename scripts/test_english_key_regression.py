"""Regression test for v0.1.1: English localization key standardization.

Verifies normalize_english_localization() collapses an existing "en-US"
entry into "en" (the default preferred key), leaves Turkish and other
languages completely untouched, and removes the stray "en-US" key.

Pure function test — no network calls, no real YouTube account needed.

Run with:
    python -m scripts.test_english_key_regression
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from youtubelocalizer.language_map import normalize_english_localization


def test_en_us_migrates_to_en() -> None:
    """Primary case from the v0.1.1 spec: {tr, en-US, de} -> {tr, en, de}."""
    before = {
        "tr": {"title": "Türkçe başlık", "description": "Türkçe açıklama"},
        "en-US": {"title": "English (US) title", "description": "English (US) description"},
        "de": {"title": "Deutscher Titel", "description": "Deutsche Beschreibung"},
    }

    result = normalize_english_localization(before, preferred_key="en")

    assert set(result.keys()) == {"tr", "en", "de"}, f"unexpected keys: {sorted(result.keys())}"
    assert "en-US" not in result, "en-US should have been removed"
    assert "en" in result, "en should exist after normalization"
    assert result["en"] == before["en-US"], "en content should match the migrated en-US content"
    assert result["tr"] == before["tr"], "Turkish metadata must be unchanged"
    assert result["de"] == before["de"], "German localization must be unchanged"
    assert "en-US" in before, "input dict must not be mutated"

    print("PASS: en-US migrated to en; tr and de untouched; input not mutated.")
    print(f"  before: {sorted(before.keys())}")
    print(f"  after:  {sorted(result.keys())}")


def test_existing_en_wins_over_stray_en_us() -> None:
    """Both keys present: keep en's own content, just drop en-US."""
    before = {
        "tr": {"title": "Türkçe başlık", "description": "Türkçe açıklama"},
        "en": {"title": "Existing EN title", "description": "Existing EN description"},
        "en-US": {"title": "Stray EN-US title", "description": "Stray EN-US description"},
    }

    result = normalize_english_localization(before, preferred_key="en")

    assert set(result.keys()) == {"tr", "en"}, f"unexpected keys: {sorted(result.keys())}"
    assert result["en"] == before["en"], "existing en content must be preserved, not overwritten by en-US"
    assert result["tr"] == before["tr"], "Turkish metadata must be unchanged"

    print("PASS: existing en preserved; stray en-US dropped.")


def test_neither_key_present_is_a_noop() -> None:
    before = {
        "tr": {"title": "Türkçe başlık", "description": "Türkçe açıklama"},
        "de": {"title": "Deutscher Titel", "description": "Deutsche Beschreibung"},
    }

    result = normalize_english_localization(before, preferred_key="en")

    assert result == before, "with no English entry at all, normalization must be a no-op"

    print("PASS: no English entry present -> no-op.")


def main() -> int:
    test_en_us_migrates_to_en()
    test_existing_en_wins_over_stray_en_us()
    test_neither_key_present_is_a_noop()
    print("\nAll English localization key regression tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
