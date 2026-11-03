"""Public aggregate API over verified, immutable DuckDB publications."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from .snapshots import Snapshot, SnapshotStore, parse_timestamp

BOROUGHS = {"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND", "UNKNOWN"}
MAX_SNAPSHOT_AGE_HOURS = 36


def _latest_attempt(data_dir: Path) -> dict | None:
    candidates = []
    for path in (data_dir / "runs").glob("*.json"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    for _, path in sorted(candidates, reverse=True):
        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            value = json.loads(path.read_text())
            if isinstance(value, dict):
                keys = ("run_id", "status", "started_at", "finished_at", "generated_at", "source_mode")
                return {key: value[key] for key in keys if key in value}
        except (OSError, ValueError):
            continue
    return None


def _metadata(snapshot: Snapshot, store: SnapshotStore) -> dict:
    manifest = snapshot.manifest
    generated = parse_timestamp(manifest["generated_at"])
    age_seconds = max(0, int((datetime.now(timezone.utc) - generated).total_seconds()))
    stale = age_seconds > MAX_SNAPSHOT_AGE_HOURS * 3600
    attempt = _latest_attempt(store.data_dir)
    # Source event dates are separate from delivery freshness: crashes can be reported late.
    return {
        "data_version": manifest["version"],
        "source_mode": manifest["source_mode"],
        "freshness": {
            "status": "stale" if stale else "current",
            "stale": stale,
            "generated_at": manifest["generated_at"],
            "snapshot_age_seconds": age_seconds,
            "stale_after_hours": MAX_SNAPSHOT_AGE_HOURS,
            "window_start": manifest["window_start"],
            "window_end": manifest["window_end"],
            "source_max_crash_date": manifest["source_max_crash_date"],
            "last_refresh_checked_at": store.last_checked_at,
            "refresh_ok": store.last_error is None,
        },
        "latest_attempt": attempt,
    }


def _selection(snapshot: Snapshot, start_date: date | None, end_date: date | None, borough: str | None):
    window_start = date.fromisoformat(snapshot.manifest["window_start"])
    window_end = date.fromisoformat(snapshot.manifest["window_end"])
    end = end_date or window_end
    start = start_date or max(window_start, end - timedelta(days=29))
    if start > end:
        raise HTTPException(422, "start_date must not follow end_date")
    if (end - start).days + 1 > 366:
        raise HTTPException(422, "date ranges must contain at most 366 days")
    if start < window_start or end > window_end:
        raise HTTPException(422, "requested dates are outside the published snapshot window")
    normalized = borough.strip().upper() if borough is not None else None
    if normalized is not None and normalized not in BOROUGHS:
        raise HTTPException(422, "borough must be a NYC borough or UNKNOWN")
    where = "crash_date BETWEEN ? AND ?"
    parameters = [start, end]
    if normalized is not None:
        where += " AND borough = ?"
        parameters.append(normalized)
    return where, parameters, {"start_date": start.isoformat(), "end_date": end.isoformat(), "borough": normalized}


def _query(snapshot: Snapshot, sql: str, parameters: list) -> list[dict]:
    try:
        with duckdb.connect(str(snapshot.database), read_only=True, config={"enable_external_access": False}) as connection:
            cursor = connection.execute(sql, parameters)
            names = [item[0] for item in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]
    except duckdb.Error as exc:
        raise HTTPException(503, "the published snapshot could not be queried") from exc


def create_app(data_dir: Path | None = None, manifest_url: str | None = None, refresh_seconds: int = 900) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("ROADSAFETY_DATA_DIR", "data"))
    manifest_url = manifest_url if manifest_url is not None else os.environ.get("ROADSAFETY_MANIFEST_URL")
    if refresh_seconds <= 0:
        raise ValueError("refresh_seconds must be positive")
    store = SnapshotStore(data_dir, manifest_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        await asyncio.to_thread(store.refresh)

        async def periodically_refresh():
            while True:
                await asyncio.sleep(refresh_seconds)
                await asyncio.to_thread(store.refresh)

        worker = asyncio.create_task(periodically_refresh())
        try:
            yield
        finally:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker

    application = FastAPI(
        title="NYC Road Safety Learning API", version="1.0.0", lifespan=lifespan,
        description="Public borough-level crash and vehicle aggregates. Check source_mode and freshness before use. "
                    "Crash dates can precede reporting dates; these data do not establish causality or individual risk.",
    )
    application.state.snapshot_store = store

    def current() -> Snapshot:
        snapshot = store.get()
        if snapshot is None:
            raise HTTPException(503, "no validated serving snapshot is available")
        return snapshot

    @application.get("/ready")
    def ready():
        """Host readiness depends on usable data, not upstream freshness or success."""
        snapshot = current()
        _query(snapshot, "SELECT 1 FROM gold_daily LIMIT 1", [])
        metadata = _metadata(snapshot, store)
        return {"status": "ready", **metadata}

    @application.get("/health")
    def health():
        snapshot = store.get()
        if snapshot is None:
            return JSONResponse(status_code=503, content={
                "status": "degraded", "reason": "no validated serving snapshot",
                "data_version": None, "source_mode": None,
                "freshness": {"status": "unavailable", "refresh_ok": False},
                "latest_attempt": _latest_attempt(data_dir),
            })
        metadata = _metadata(snapshot, store)
        attempt = metadata["latest_attempt"] or {}
        failed = str(attempt.get("status", "")).lower() in {"failed", "error", "blocked", "quarantined"}
        try:
            _query(snapshot, "SELECT 1 FROM gold_daily LIMIT 1", [])
            readable = True
        except HTTPException:
            readable = False
        degraded = metadata["freshness"]["stale"] or not metadata["freshness"]["refresh_ok"] or failed or not readable
        return JSONResponse(status_code=503 if degraded else 200, content={
            "status": "degraded" if degraded else "ok", "snapshot_readable": readable, **metadata,
        })

    @application.get("/v1/data-status")
    def data_status():
        snapshot = current()
        return {**_metadata(snapshot, store), "quality": snapshot.manifest["quality"],
                "schema_version": snapshot.manifest["schema_version"],
                "refresh_error": store.last_error}

    @application.get("/v1/collisions/summary")
    def collision_summary(
        start_date: date | None = None, end_date: date | None = None, borough: str | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 1000,
    ):
        snapshot = current()
        where, params, selection = _selection(snapshot, start_date, end_date, borough)
        sums = ", ".join(f"CAST(COALESCE(SUM({field}), 0) AS BIGINT) AS {field}" for field in
                         ("collisions", "injured", "killed", "missing_location"))
        totals = _query(snapshot, f"SELECT {sums} FROM gold_daily WHERE {where}", params)[0]
        rows = _query(snapshot, f"SELECT borough, {sums} FROM gold_daily WHERE {where} GROUP BY borough ORDER BY borough LIMIT ?", params + [limit])
        return {**_metadata(snapshot, store), "selection": selection, "totals": totals, "data": rows}

    @application.get("/v1/collisions/trends")
    def collision_trends(
        start_date: date | None = None, end_date: date | None = None, borough: str | None = None,
        granularity: Literal["day", "month"] = "day",
        limit: Annotated[int, Query(ge=1, le=1000)] = 1000,
    ):
        snapshot = current()
        where, params, selection = _selection(snapshot, start_date, end_date, borough)
        rows = _query(snapshot, f"""
            SELECT CAST(date_trunc(?, crash_date) AS DATE) AS period,
                   CAST(SUM(collisions) AS BIGINT) AS collisions,
                   CAST(SUM(injured) AS BIGINT) AS injured, CAST(SUM(killed) AS BIGINT) AS killed,
                   CAST(SUM(missing_location) AS BIGINT) AS missing_location
            FROM gold_daily WHERE {where} GROUP BY period ORDER BY period LIMIT ?
        """, [granularity, *params, limit])
        return {**_metadata(snapshot, store), "selection": {**selection, "granularity": granularity}, "data": rows}

    @application.get("/v1/vehicles/summary")
    def vehicle_summary(
        start_date: date | None = None, end_date: date | None = None, borough: str | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 1000,
    ):
        snapshot = current()
        where, params, selection = _selection(snapshot, start_date, end_date, borough)
        rows = _query(snapshot, f"""
            SELECT vehicle_type, CAST(SUM(involved_vehicles) AS BIGINT) AS involved_vehicles
            FROM gold_vehicles WHERE {where} GROUP BY vehicle_type ORDER BY involved_vehicles DESC, vehicle_type LIMIT ?
        """, params + [limit])
        total = _query(snapshot, f"SELECT CAST(COALESCE(SUM(involved_vehicles), 0) AS BIGINT) AS involved_vehicles FROM gold_vehicles WHERE {where}", params)[0]
        return {**_metadata(snapshot, store), "selection": selection, "totals": total, "data": rows}

    return application


app = create_app()
