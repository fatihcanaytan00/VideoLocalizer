from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_QUOTA_EXCEEDED = "quota_exceeded"

_Key = Tuple[str, str, str]  # (account, video_id, language_code)


class CaptionProgressError(Exception):
    """Raised when the caption progress state file can't be read or written."""


@dataclass(frozen=True)
class CaptionProgressRecord:
    account: str
    video_id: str
    language_code: str
    status: str
    timestamp: str  # ISO-8601 UTC


class CaptionProgressStore:
    """Tracks per-(account, video, language) caption upload status in a
    single local JSON file — not a database, just a lightweight record of
    what's already been done, so a repeated or resumed run can skip
    languages already uploaded successfully instead of re-uploading them
    (and burning more quota on unchanged content).
    """

    def __init__(self, path: Path):
        self._path = path

    def get_status(self, account: str, video_id: str, language_code: str) -> Optional[str]:
        records = self._load()
        record = records.get((account, video_id, language_code))
        return record.status if record else None

    def record(self, account: str, video_id: str, language_code: str, status: str) -> None:
        records = self._load()
        key: _Key = (account, video_id, language_code)
        records[key] = CaptionProgressRecord(
            account=account,
            video_id=video_id,
            language_code=language_code,
            status=status,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._save(records)

    def _load(self) -> Dict[_Key, CaptionProgressRecord]:
        if not self._path.is_file():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CaptionProgressError(f"Failed to read '{self._path}': {exc}") from exc

        if not isinstance(raw, list):
            raise CaptionProgressError(f"'{self._path}' must contain a JSON list.")

        records: Dict[_Key, CaptionProgressRecord] = {}
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                record = CaptionProgressRecord(
                    account=entry["account"],
                    video_id=entry["video_id"],
                    language_code=entry["language_code"],
                    status=entry["status"],
                    timestamp=entry["timestamp"],
                )
            except KeyError:
                logger.warning("Skipping malformed caption progress entry: %r", entry)
                continue
            key = (record.account, record.video_id, record.language_code)
            records[key] = record
        return records

    def _save(self, records: Dict[_Key, CaptionProgressRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(r) for r in records.values()]
        try:
            self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            raise CaptionProgressError(f"Failed to write '{self._path}': {exc}") from exc
