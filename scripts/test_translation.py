"""Standalone translator check: translates a sample sentence into every
configured target language and prints the result. Does not touch YouTube.

Run with:
    python -m scripts.test_translation
"""
from __future__ import annotations

import logging
import sys

# Console codepages (e.g. Windows cp1254) can't represent most target-language
# scripts (Arabic, Hindi, Japanese, ...) and raise UnicodeEncodeError on print()
# otherwise. Redirected/piped output is unaffected either way.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from youtubelocalizer.config import ConfigError, load_config
from youtubelocalizer.language_map import LanguageMapError, get_provider_code
from youtubelocalizer.translator import TranslationError, get_translator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SAMPLE_TEXT_TR = "Bugün hava çok güzel, dışarıda yürüyüşe çıkmak istiyorum."


def main() -> int:
    try:
        config = load_config("config/config.yaml")
    except ConfigError as exc:
        logger.error("Config error: %s", exc)
        return 1

    try:
        translator = get_translator(config.translation.provider)
    except TranslationError as exc:
        logger.error("Translator setup error: %s", exc)
        return 1

    try:
        source_code = get_provider_code(config.source_language)
    except LanguageMapError as exc:
        logger.error("Language map error: %s", exc)
        return 1

    print(f"Source ({config.source_language}): {SAMPLE_TEXT_TR}\n")

    failures = []
    for canonical_target in config.target_languages:
        try:
            target_code = get_provider_code(canonical_target)
            translated = translator.translate(SAMPLE_TEXT_TR, source_code, target_code)
            print(f"[{canonical_target}] {translated}")
        except (LanguageMapError, TranslationError) as exc:
            failures.append(canonical_target)
            print(f"[{canonical_target}] FAILED: {exc}")

    print()
    if failures:
        logger.error("Failed languages: %s", failures)
        return 1

    logger.info("All %d target languages translated successfully.", len(config.target_languages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
