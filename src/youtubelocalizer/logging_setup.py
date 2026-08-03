from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import LoggingConfig

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def configure_logging(logging_config: LoggingConfig, run_label: str) -> Path:
    """Configure console + per-run file logging. Returns the log file path.

    Each run gets its own timestamped file under logging_config.directory,
    named with `run_label` (typically the account name) so concurrent runs
    against different accounts don't interleave into the same file.
    """
    log_dir = Path(logging_config.directory)
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in run_label)
    log_file = log_dir / f"run_{timestamp}_{safe_label}.log"

    level = getattr(logging, logging_config.level)
    formatter = logging.Formatter(LOG_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return log_file
