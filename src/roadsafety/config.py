"""Small, explicit settings shared by scripts and hosted services."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def months_before(day: date, months: int) -> date:
    import calendar
    absolute = day.year * 12 + day.month - 1 - months
    year, month0 = divmod(absolute, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    retention_months: int = 24
    refresh_days: int = 90

    def ensure(self) -> None:
        for folder in ("raw", "runs", "reports", "published", "quarantine", "incidents"):
            (self.data_dir / folder).mkdir(parents=True, exist_ok=True)
