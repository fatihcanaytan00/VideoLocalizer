from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional, Sequence

# Console codepages (e.g. Windows cp1254) can't represent most target-language
# scripts (Arabic, Hindi, Japanese, ...) and raise UnicodeEncodeError on print()
# otherwise. Redirected/piped output is unaffected either way.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

from . import __version__
from .accounts import AccountsError, get_account, load_accounts
from .auth import AuthError, get_authenticated_service
from .config import ConfigError, load_config
from .logging_setup import configure_logging
from .orchestrator import RunResult, run_localization
from .translator import TranslationError, get_translator
from .youtube_client import YouTubeClientError

_EXAMPLES = """\
examples:
  # Localize the latest upload on the "main_channel" account
  python -m youtubelocalizer.main --account main_channel

  # Localize a specific video instead of the latest upload
  python -m youtubelocalizer.main --account main_channel --video-id dQw4w9WgXcQ

  # Show the installed version
  python -m youtubelocalizer.main --version

account names come from config/accounts.yaml; target languages, source
language, and protected terms come from config/config.yaml.
"""


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="youtubelocalizer",
        description="YouTubeLocalizer: translate a video's title and description "
        "into multiple languages and write them back as YouTube localizations.",
        epilog=_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"YouTubeLocalizer v{__version__}",
    )
    parser.add_argument(
        "--account",
        required=True,
        metavar="NAME",
        help="Account profile to run, as defined in config/accounts.yaml (required).",
    )
    parser.add_argument(
        "--video-id",
        default=None,
        metavar="VIDEO_ID",
        help="Specific YouTube video ID to localize. If omitted, uses the "
        "channel's most recent upload.",
    )
    return parser.parse_args(argv)


def print_summary(result: RunResult) -> None:
    succeeded = result.succeeded
    failed = result.failed
    with_warnings = [r for r in succeeded if r.warnings]

    print("\n=== Localization Summary ===")
    print(f"Video: {result.video.title} ({result.video.video_id})")

    print("\nMetadata:")
    print(f"{len(succeeded)}/{len(result.language_results)} languages updated")
    if failed:
        print(f"Languages failed ({len(failed)}):")
        for r in failed:
            print(f"  - {r.display_name}: {r.error}")
    if with_warnings:
        print(f"Quality warnings ({len(with_warnings)}):")
        for r in with_warnings:
            print(f"  - {r.display_name}: {'; '.join(r.warnings)}")

    print("\nCaptions:")
    cap = result.caption_result
    if not cap.attempted:
        print(f"Skipped ({cap.skip_reason})")
    else:
        for r in cap.language_results:
            print(f"{r.display_name} {_caption_status_text(r)}")


_CAPTION_STATUS_SUFFIX = {
    "success": "✅",
    "skipped_existing": "✅ (already uploaded)",
    "quota_exceeded": "❌ quota exceeded",
    "not_attempted": "⏳ not attempted",
}


def _caption_status_text(result) -> str:
    if result.status == "failed":
        return f"❌ ({result.error})" if result.error else "❌"
    return _CAPTION_STATUS_SUFFIX.get(result.status, "?")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    try:
        config = load_config("config/config.yaml")
        profiles = load_accounts("config/accounts.yaml")
        account = get_account(profiles, args.account)
    except (ConfigError, AccountsError) as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    log_file = configure_logging(config.logging, run_label=account.name)
    logger.info("Logging to %s", log_file)

    try:
        youtube = get_authenticated_service(account)
    except AuthError as exc:
        logger.error("Authentication error for account '%s': %s", account.name, exc)
        return 1

    try:
        translator = get_translator(config.translation.provider)
    except TranslationError as exc:
        logger.error("Translator setup error: %s", exc)
        return 1

    try:
        result = run_localization(youtube, config, translator, account.name, video_id=args.video_id)
    except YouTubeClientError as exc:
        logger.error("Localization run failed for account '%s': %s", account.name, exc)
        return 1

    print_summary(result)
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
