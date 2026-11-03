"""Evidence-based source checks and bounded acquisition of NYC Open Data.

Live access is separate from the synthetic fixtures used by the course. Metadata
verification establishes the current fields and anonymous access, not legal
advice, an atomic source snapshot, or complete change-data capture.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://data.cityofnewyork.us"
SOURCES = {
    "crashes": {
        "dataset_id": "h9gi-nx95",
        "key": "collision_id",
        "required": (
            "collision_id", "crash_date", "number_of_persons_injured",
            "number_of_persons_killed",
        ),
    },
    "vehicles": {
        "dataset_id": "bm4k-52h4",
        "key": "unique_id",
        "required": ("unique_id", "collision_id", "crash_date"),
    },
}


class AcquisitionError(RuntimeError):
    """A source gate, response, or completeness check failed."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    value = response.headers.get("Retry-After", "") if response is not None else ""
    try:
        seconds = float(value)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            seconds = (parsed - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            seconds = 0.5 * 2**attempt
    return min(max(seconds, 0), 30)


def _get(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    """Preserve TLS/proxy settings; retry transient failures at most twice."""
    for attempt in range(3):
        response = None
        try:
            response = client.get(url, **kwargs)
            if response.status_code == 429 or 500 <= response.status_code <= 599:
                if attempt < 2:
                    time.sleep(_retry_delay(response, attempt))
                    continue
            response.raise_for_status()
            return response
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(_retry_delay(None, attempt))
    raise AssertionError("retry loop exhausted without an outcome")


def _metadata_fields(metadata: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    columns = metadata.get("columns")
    if not isinstance(columns, list):
        raise AcquisitionError("Metadata has no column inventory")
    names = sorted({c["fieldName"] for c in columns if isinstance(c, dict)
                    and isinstance(c.get("fieldName"), str)})
    missing = sorted(set(required) - set(names))
    if missing:
        raise AcquisitionError(f"Required source columns missing: {', '.join(missing)}")
    return names


def _evidence(metadata: dict[str, Any]) -> dict[str, Any]:
    """Copy publisher evidence verbatim; do not manufacture missing terms."""
    details = metadata.get("metadata")
    custom = details.get("custom_fields", {}) if isinstance(details, dict) else {}
    cadence: dict[str, Any] = {}
    terms: dict[str, Any] = {}
    for group, entries in custom.items() if isinstance(custom, dict) else []:
        if not isinstance(entries, dict):
            continue
        for key, value in entries.items():
            label = f"{group}.{key}"
            if any(word in key.lower() for word in ("frequency", "cadence", "update")):
                cadence[label] = value
            if any(word in key.lower() for word in ("license", "licence", "terms", "usage")):
                terms[label] = value
    for key in ("license", "licenseId", "licenseUrl", "termsOfUse", "termsOfUseUrl"):
        if metadata.get(key):
            terms[key] = metadata[key]
    return {
        "owner_evidence": {key: metadata[key] for key in (
            "attribution", "attributionLink", "owner", "provenance"
        ) if key in metadata},
        "cadence_evidence": cadence,
        "terms_evidence": terms,
        "terms_status": "publisher_metadata_present" if terms else "unresolved",
        "rows_updated_at": metadata.get("rowsUpdatedAt"),
        "column_types": {
            column["fieldName"]: column.get("dataTypeName")
            for column in metadata.get("columns", [])
            if isinstance(column, dict) and isinstance(column.get("fieldName"), str)
        },
    }


def verify_sources(data_dir: Path, client: httpx.Client | None = None) -> dict[str, Any]:
    """Save current schema/access evidence and return a report, including failures.

    ``verified`` concerns schema and anonymous access only. Live acquisition also
    requires a separately recorded ``terms_acknowledged`` value. Absence of a
    licence in metadata remains an explicit unresolved issue after acknowledgment.
    """
    data_dir = Path(data_dir)
    path = data_dir / "source_verification.json"
    try:
        previous = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        previous = {}
    report: dict[str, Any] = {
        "status": "unverified", "checked_at": _now(), "data_origin": "live",
        "terms_acknowledged": False, "sources": {}, "limitations": [],
        "scope": "Current schema and anonymous access; not a publisher SLA or legal review.",
    }
    manager = nullcontext(client) if client is not None else httpx.Client(timeout=30)
    with manager as active:
        for name, source in SOURCES.items():
            dataset_id = source["dataset_id"]
            entry: dict[str, Any] = {
                "dataset_id": dataset_id, "status": "unverified",
                "metadata_url": f"{BASE_URL}/api/views/{dataset_id}.json",
                "data_url": f"{BASE_URL}/resource/{dataset_id}.json",
                "required_columns": list(source["required"]),
            }
            report["sources"][name] = entry
            try:
                metadata = _get(active, entry["metadata_url"]).json()
                if not isinstance(metadata, dict):
                    raise AcquisitionError("Metadata response is not an object")
                names = _metadata_fields(metadata, source["required"])
                entry.update(_evidence(metadata))
                entry["title"] = metadata.get("name")
                entry["columns"] = names
                entry["column_descriptions"] = {
                    column["fieldName"]: {
                        "description": column["description"],
                        "source": entry["metadata_url"],
                    }
                    for column in metadata["columns"]
                    if isinstance(column, dict)
                    and isinstance(column.get("fieldName"), str)
                    and isinstance(column.get("description"), str)
                    and column["description"].strip()
                }
                entry["schema_fingerprint"] = hashlib.sha256(
                    json.dumps(names).encode()
                ).hexdigest()
                probe = _get(active, entry["data_url"], params={
                    "$limit": 1, "$order": f"{source['key']} ASC",
                }).json()
                if not isinstance(probe, list) or not probe:
                    raise AcquisitionError("Anonymous sample probe returned no records")
                if not isinstance(probe[0], dict) or source["key"] not in probe[0]:
                    raise AcquisitionError("Sample does not contain the expected business key")
                entry["probe_rows"] = len(probe)
                entry["status"] = "verified"
                if not entry["cadence_evidence"]:
                    report["limitations"].append(f"{name}: update cadence absent from metadata")
                if not entry["terms_evidence"]:
                    report["limitations"].append(f"{name}: source terms require documentation review")
            except (httpx.HTTPError, AcquisitionError, ValueError, TypeError) as error:
                entry["error"] = f"{type(error).__name__}: {error}"
    if all(s["status"] == "verified" for s in report["sources"].values()):
        report["status"] = "verified"
        previous_sources = previous.get("sources", {})
        same_terms = all(
            previous_sources.get(name, {}).get("terms_evidence") == entry.get("terms_evidence")
            for name, entry in report["sources"].items()
        )
        report["terms_acknowledged"] = bool(previous.get("terms_acknowledged") and same_terms)
    _write_json(path, report)
    return report


def _live_gate(data_dir: Path) -> dict[str, Any]:
    try:
        gate = json.loads((data_dir / "source_verification.json").read_text())
    except (FileNotFoundError, ValueError) as error:
        raise AcquisitionError("Run source verification before live acquisition") from error
    if gate.get("status") != "verified" or not gate.get("terms_acknowledged"):
        raise AcquisitionError("Live acquisition needs verified schema/access and acknowledged source terms")
    if gate.get("data_origin") != "live":
        raise AcquisitionError("Synthetic verification cannot authorize a live source")
    for name, source in SOURCES.items():
        recorded = gate.get("sources", {}).get(name, {})
        if recorded.get("dataset_id") != source["dataset_id"] or recorded.get("status") != "verified":
            raise AcquisitionError(f"Verification for {name} is missing or belongs to another source")
    return gate


def acquire_live(
    data_dir: Path,
    start: date,
    end: date,
    client: httpx.Client | None = None,
    *,
    page_size: int = 5000,
    max_pages: int = 2000,
) -> dict[str, Any]:
    """Acquire both sources for inclusive local crash dates, or fail as a unit.

    Pages are immutable. A failed run retains its raw evidence with ``complete``
    false and raises AcquisitionError; callers must not reconcile or publish it.
    Stable keyset pagination reduces paging errors but does not make the remote
    source transactionally consistent while publishers are editing it.
    """
    data_dir = Path(data_dir)
    gate = _live_gate(data_dir)
    if start > end or not 1 <= page_size <= 50000 or max_pages < 1:
        raise ValueError("Invalid date window, page size, or page bound")
    run_id = uuid.uuid4().hex
    root = data_dir / "landing" / "live" / run_id
    root.mkdir(parents=True, exist_ok=False)
    provenance: dict[str, Any] = {
        "run_id": run_id, "data_origin": "live", "start": start.isoformat(),
        "end": end.isoformat(), "acquired_at": _now(), "complete": False,
        "atomic_source_snapshot": False, "sources": {},
        "verification_checked_at": gate.get("checked_at"),
        "limitations": ["Source records can change during pagination; this is not complete CDC."],
    }
    result: dict[str, Any] = {"crashes": [], "vehicles": [], "provenance": provenance}
    manager = nullcontext(client) if client is not None else httpx.Client(timeout=30)
    try:
        with manager as active:
            for name, source in SOURCES.items():
                dataset_id, key = source["dataset_id"], source["key"]
                metadata = _get(active, f"{BASE_URL}/api/views/{dataset_id}.json").json()
                names = _metadata_fields(metadata, source["required"])
                evidence = _evidence(metadata)
                if evidence["terms_evidence"] != gate["sources"][name].get("terms_evidence"):
                    raise AcquisitionError(f"{name} source terms metadata changed; review and verify again")
                source_dir = root / name
                source_dir.mkdir()
                manifest: dict[str, Any] = {
                    "dataset_id": dataset_id, "columns": names,
                    "complete": False, "pages": [], "row_count": 0,
                }
                provenance["sources"][name] = manifest
                cursor = -1
                for page_number in range(max_pages):
                    where = (
                        f"crash_date >= '{start.isoformat()}T00:00:00' AND "
                        f"crash_date < '{(end + timedelta(days=1)).isoformat()}T00:00:00' "
                        f"AND {key} > {cursor}"
                    )
                    response = _get(active, f"{BASE_URL}/resource/{dataset_id}.json", params={
                        "$where": where, "$order": f"{key} ASC", "$limit": page_size,
                    })
                    raw = response.content
                    page_path = source_dir / f"{page_number:06d}.json"
                    with page_path.open("xb") as stream:
                        stream.write(raw)
                    manifest["pages"].append({
                        "path": str(page_path.relative_to(data_dir)),
                        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                    })
                    rows = response.json()
                    if not isinstance(rows, list) or len(rows) > page_size:
                        raise AcquisitionError(f"{name}: expected a bounded JSON array")
                    for row in rows:
                        value = row.get(key) if isinstance(row, dict) else None
                        if value is None or not re.fullmatch(r"\d+", str(value)):
                            raise AcquisitionError(f"{name}: missing or non-integer {key}")
                        integer_key = int(value)
                        if integer_key <= cursor:
                            raise AcquisitionError(f"{name}: duplicate or unordered pagination key {key}")
                        cursor = integer_key
                        try:
                            observed_date = date.fromisoformat(str(row["crash_date"])[:10])
                        except (KeyError, ValueError) as error:
                            raise AcquisitionError(f"{name}: missing or invalid crash_date") from error
                        if not start <= observed_date <= end:
                            raise AcquisitionError(f"{name}: response escaped the requested date window")
                        result[name].append(row)
                    manifest["row_count"] += len(rows)
                    if len(rows) < page_size:
                        manifest["complete"] = True
                        break
                if not manifest["complete"]:
                    raise AcquisitionError(f"{name}: maximum page bound reached without exhaustion")
        provenance["complete"] = True
        provenance["finished_at"] = _now()
        _write_json(root / "manifest.json", provenance)
        return result
    except Exception as error:
        provenance["error"] = f"{type(error).__name__}: {error}"
        provenance["finished_at"] = _now()
        _write_json(root / "manifest.json", provenance)
        if isinstance(error, AcquisitionError):
            raise
        raise AcquisitionError(f"Live acquisition incomplete: {type(error).__name__}: {error}") from error
