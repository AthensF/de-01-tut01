"""Bounded live acquisition and profiling before a production backfill."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from roadsafety.config import atomic_json, sha256_file, utc_now
from roadsafety.ingest import acquire_live
from roadsafety.pipeline import _clean
from roadsafety.reports import profile


def run_pilot(data_dir: Path, start: date, end: date) -> dict:
    """Acquire at most 31 days, retain original evidence, and measure the batch.

    Source verification and source-use acknowledgment remain mandatory. This
    command never writes a warehouse, serving snapshot, or publication manifest.
    """
    if start > end or (end - start).days >= 31:
        raise ValueError("A live pilot must span between 1 and 31 inclusive days")
    data_dir = Path(data_dir)
    existing = data_dir / "published" / "manifest.json"
    if existing.exists():
        raise ValueError("Use a separate pilot directory without a published warehouse")
    # Deliberately small pages exercise pagination during the pilot rather than
    # letting a successful first page conceal a broken continuation cursor.
    records = acquire_live(data_dir, start, end, page_size=500)
    if not records.get("provenance", {}).get("complete"):
        raise ValueError("Incomplete acquisition cannot become a profiling batch")
    run_id = "pilot-" + records["provenance"]["run_id"]
    raw = data_dir / "raw" / run_id
    raw.mkdir(parents=True, exist_ok=False)
    for source in ("crashes", "vehicles"):
        atomic_json(raw / f"{source}.json", records[source])
    provenance = {
        **records["provenance"], "source_mode": "live", "data_origin": "publisher",
        "window_start": str(start), "window_end": str(end),
        "purpose": "Bounded source-profiling pilot; not the full production history",
        "checksums": {source: sha256_file(raw / f"{source}.json") for source in ("crashes", "vehicles")},
    }
    atomic_json(raw / "provenance.json", provenance)
    cleaned, quarantined, extras = _clean(records, start, end)
    atomic_json(data_dir / "quarantine" / f"{run_id}.json", quarantined)
    result = {
        "checked_at": utc_now(), "source_mode": "live", "scope": "profiling_only",
        "window_start": str(start), "window_end": str(end), "batch": run_id,
        "raw_rows": {name: len(records[name]) for name in ("crashes", "vehicles")},
        "valid_rows": {name: len(cleaned[name]) for name in ("crashes", "vehicles")},
        "quarantined_count": len(quarantined), "observed_extra_fields": extras,
        "required_rule_outcome": "passed" if cleaned["crashes"] and not quarantined else "blocked",
        "profile": str(profile(data_dir)), "production_publication_performed": False,
    }
    atomic_json(data_dir / "pilot-validation.json", result)
    return result
