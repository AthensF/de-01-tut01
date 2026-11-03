"""Build a candidate warehouse, check it, then publish an immutable serving file.

Refreshing a date window replaces that complete window, not just new identifiers.
Weekly full reconciliation is necessary for older corrections and removals.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from roadsafety.config import Settings, atomic_json, months_before, sha256_file, utc_now
from roadsafety.fixtures import FIXTURE_AS_OF, fixture_records

REQUIRED = {
    "crashes": {"collision_id", "crash_date", "number_of_persons_injured", "number_of_persons_killed"},
    "vehicles": {"unique_id", "collision_id", "crash_date"},
}
BOROUGHS = {"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"}
LINEAGE = {
    "bronze.crashes": ["landing.crashes"], "bronze.vehicles": ["landing.vehicles"],
    "silver_clean.crashes": ["bronze.crashes"], "silver_clean.vehicles": ["bronze.vehicles"],
    "silver_core.crashes": ["silver_clean.crashes"],
    "silver_core.vehicles": ["silver_clean.vehicles", "silver_core.crashes"],
    "gold.daily": ["silver_core.crashes"],
    "gold.vehicle_daily": ["silver_core.crashes", "silver_core.vehicles"],
}


class QualityError(ValueError):
    """Candidate failed a publication gate; previous publication is retained."""


@contextmanager
def pipeline_lock(data_dir: Path):
    with (data_dir / ".pipeline.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QualityError("Another pipeline is running for this data directory") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _date(value) -> date:
    return date.fromisoformat(str(value)[:10])


def _integer(value) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError("required count is missing or boolean")
    number = int(str(value))
    if number < 0:
        raise ValueError("count is negative")
    return number


def _coordinates(row: dict):
    try:
        lat, lon = float(row["latitude"]), float(row["longitude"])
        # NYC published coordinates, with invalid/zero locations kept as unknown.
        if 40 <= lat <= 42 and -75 <= lon <= -71:
            return lat, lon, True
    except (KeyError, TypeError, ValueError):
        pass
    return None, None, False


def _clean(records: dict, start: date, end: date):
    cleaned = {"crashes": [], "vehicles": []}
    quarantined = []
    additive = {}
    for source, required in REQUIRED.items():
        rows = records.get(source)
        if not isinstance(rows, list):
            raise QualityError(f"{source}: source must be a JSON array")
        seen = set()
        extra = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                quarantined.append({"source": source, "row": index, "reason": "not an object"})
                continue
            missing = required - row.keys()
            if missing:
                quarantined.append({"source": source, "row": index, "reason": f"missing required fields: {sorted(missing)}"})
                continue
            extra.update(row.keys() - required)
            try:
                key = str(row["collision_id" if source == "crashes" else "unique_id"]).strip()
                parent = str(row["collision_id"]).strip()
                if not key or key == "None" or not parent or parent == "None":
                    raise ValueError("empty identifier")
                if key in seen:
                    raise ValueError(f"duplicate key {key}")
                seen.add(key)
                day = _date(row["crash_date"])
                if not start <= day <= end:
                    continue
                if source == "crashes":
                    borough = str(row.get("borough") or "").strip().upper()
                    borough = borough if borough in BOROUGHS else "UNKNOWN"
                    lat, lon, has_location = _coordinates(row)
                    cleaned[source].append((key, day, borough, _integer(row["number_of_persons_injured"]),
                                             _integer(row["number_of_persons_killed"]), lat, lon, has_location))
                else:
                    kind = str(row.get("vehicle_type") or "UNKNOWN").strip() or "UNKNOWN"
                    cleaned[source].append((key, parent, day, kind))
            except (ValueError, TypeError, OverflowError) as exc:
                quarantined.append({"source": source, "row": index, "reason": str(exc), "record": row})
        additive[source] = sorted(extra)
    return cleaned, quarantined, additive


def _create_schema(con):
    for name in ("bronze", "silver_clean", "silver_core", "gold"):
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {name}")
    con.execute("CREATE TABLE IF NOT EXISTS bronze.crashes (record_key VARCHAR PRIMARY KEY, crash_date DATE, payload JSON)")
    con.execute("CREATE TABLE IF NOT EXISTS bronze.vehicles (record_key VARCHAR PRIMARY KEY, crash_date DATE, payload JSON)")
    con.execute("""CREATE TABLE IF NOT EXISTS silver_clean.crashes (
        collision_id VARCHAR PRIMARY KEY, crash_date DATE, borough VARCHAR,
        injured BIGINT, killed BIGINT, latitude DOUBLE, longitude DOUBLE, has_location BOOLEAN)""")
    con.execute("""CREATE TABLE IF NOT EXISTS silver_clean.vehicles (
        unique_id VARCHAR PRIMARY KEY, collision_id VARCHAR, crash_date DATE, vehicle_type VARCHAR)""")


def _build(con, records, clean, window_start, horizon_start, as_of):
    _create_schema(con)
    for source in REQUIRED:
        # Replace only the complete acquired window; enforce the rolling horizon.
        for schema in ("bronze", "silver_clean"):
            con.execute(f"DELETE FROM {schema}.{source} WHERE crash_date >= ? OR crash_date < ? OR crash_date > ?",
                        [window_start, horizon_start, as_of])
        keys = {r[0] for r in clean[source]}
        key_column = "collision_id" if source == "crashes" else "unique_id"
        # A corrected record may move into the refreshed window from older history.
        if keys:
            con.execute("CREATE OR REPLACE TEMP TABLE incoming_keys AS SELECT unnest(?::VARCHAR[]) AS key", [sorted(keys)])
            con.execute(f"DELETE FROM bronze.{source} WHERE record_key IN (SELECT key FROM incoming_keys)")
            con.execute(f"DELETE FROM silver_clean.{source} WHERE {key_column} IN (SELECT key FROM incoming_keys)")
        payloads = []
        for row in records[source]:
            key = str(row[key_column]).strip()
            if key in keys:
                payloads.append((key, _date(row["crash_date"]), json.dumps({k: None if v is None else str(v) for k,v in row.items()})))
        if payloads:
            con.executemany(f"INSERT INTO bronze.{source} VALUES (?,?,?)", payloads)
        if clean[source]:
            placeholders = ",".join("?" for _ in clean[source][0])
            con.executemany(f"INSERT INTO silver_clean.{source} VALUES ({placeholders})", clean[source])
    sql = """
CREATE OR REPLACE TABLE silver_core.crashes AS SELECT * FROM silver_clean.crashes;
CREATE OR REPLACE TABLE silver_core.vehicles AS SELECT * FROM silver_clean.vehicles;
CREATE OR REPLACE TABLE silver_core.dim_borough AS SELECT DISTINCT borough FROM silver_core.crashes;
CREATE OR REPLACE TABLE gold.daily AS
 SELECT crash_date, borough, COUNT(*)::BIGINT AS collisions,
        SUM(injured)::BIGINT AS injured, SUM(killed)::BIGINT AS killed,
        SUM(CASE WHEN has_location THEN 0 ELSE 1 END)::BIGINT AS missing_location
 FROM silver_core.crashes GROUP BY crash_date, borough;
CREATE OR REPLACE TABLE gold.vehicle_daily AS
 SELECT c.crash_date, c.borough, v.vehicle_type, COUNT(*)::BIGINT AS involved_vehicles
 FROM silver_core.vehicles v JOIN silver_core.crashes c USING (collision_id)
 GROUP BY c.crash_date, c.borough, v.vehicle_type;
CREATE OR REPLACE VIEW gold_daily AS SELECT * FROM gold.daily;
CREATE OR REPLACE VIEW gold_vehicles AS SELECT * FROM gold.vehicle_daily;
"""
    con.execute(sql)
    return sql


def run_pipeline(data_dir: Path, mode: str = "fixture", as_of: date | None = None,
                 full_reconcile: bool = False, input_dir: Path | None = None) -> dict:
    data_dir = Path(data_dir)
    Settings(data_dir).ensure()
    if mode not in {"fixture", "live"}:
        raise ValueError("mode must be fixture or live")
    as_of = as_of or (FIXTURE_AS_OF if mode == "fixture" else datetime.now(ZoneInfo("America/New_York")).date())
    horizon = months_before(as_of, 24)
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:10]
    candidate = data_dir / f"candidate-{run_id}.duckdb"
    run_file = data_dir / "runs" / f"{run_id}.json"
    run = {"run_id": run_id, "status": "running", "started_at": utc_now(), "source_mode": mode,
           "data_origin": "synthetic" if mode == "fixture" else "publisher",
           "as_of": str(as_of), "full_reconcile": full_reconcile}
    atomic_json(run_file, run)
    try:
        with pipeline_lock(data_dir):
            manifest_path = data_dir / "published" / "manifest.json"
            previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
            if previous and previous["source_mode"] != mode:
                raise QualityError("Fixture and live histories must use separate data directories")
            if previous and str(as_of) < previous["window_end"]:
                raise QualityError("A run cannot replace a newer publication with an older as_of date")
            warehouse = data_dir / "warehouse.duckdb"
            window_start = horizon if full_reconcile or not warehouse.exists() else max(horizon, as_of - timedelta(days=89))
            if input_dir:
                records = {name: json.loads((Path(input_dir) / f"{name}.json").read_text()) for name in REQUIRED}
                provenance_file = Path(input_dir) / "provenance.json"
                records["provenance"] = json.loads(provenance_file.read_text()) if provenance_file.exists() else {"complete": True, "data_origin": "synthetic"}
                if mode != "fixture":
                    raise QualityError("Local input overrides are only permitted for synthetic fixture mode")
            elif mode == "fixture":
                records = fixture_records(as_of)
            else:
                from roadsafety.ingest import acquire_live
                records = acquire_live(data_dir, window_start, as_of)
            if not records.get("provenance", {}).get("complete", False):
                raise QualityError("Acquisition incomplete: refusing to reconcile or publish")
            raw = data_dir / "raw" / run_id
            raw.mkdir()
            for source in REQUIRED:
                atomic_json(raw / f"{source}.json", records[source])
            provenance = {**records["provenance"], "run_id": run_id, "source_mode": mode,
                          "data_origin": "synthetic" if mode == "fixture" else "publisher",
                          "window_start": str(window_start), "window_end": str(as_of),
                          "checksums": {s: sha256_file(raw / f"{s}.json") for s in REQUIRED}}
            atomic_json(raw / "provenance.json", provenance)
            run["raw_path"] = str(raw)
            clean, quarantined, additive = _clean(records, window_start, as_of)
            atomic_json(data_dir / "quarantine" / f"{run_id}.json", quarantined)
            if quarantined:
                raise QualityError(f"{len(quarantined)} invalid records quarantined; candidate publication blocked")
            if not clean["crashes"]:
                raise QualityError("Empty crash extraction cannot replace a published window")
            if warehouse.exists():
                shutil.copy2(warehouse, candidate)
            with duckdb.connect(str(candidate)) as con:
                con.execute("BEGIN TRANSACTION")
                sql = _build(con, records, clean, window_start, horizon, as_of)
                totals = con.execute("SELECT COUNT(*), COALESCE(SUM(injured),0), COALESCE(SUM(killed),0) FROM silver_core.crashes").fetchone()
                gold_totals = con.execute("SELECT SUM(collisions),SUM(injured),SUM(killed) FROM gold.daily").fetchone()
                if tuple(totals) != tuple(gold_totals):
                    raise QualityError("Gold totals do not reconcile to crash facts")
                orphans = con.execute("SELECT COUNT(*) FROM silver_core.vehicles v ANTI JOIN silver_core.crashes c USING(collision_id)").fetchone()[0]
                vehicles = con.execute("SELECT COUNT(*) FROM silver_core.vehicles").fetchone()[0]
                missing_location = con.execute("SELECT COUNT(*) FROM silver_core.crashes WHERE NOT has_location").fetchone()[0]
                unknown = con.execute("SELECT COUNT(*) FROM silver_core.crashes WHERE borough='UNKNOWN'").fetchone()[0]
                maximum = con.execute("SELECT MAX(crash_date) FROM silver_core.crashes").fetchone()[0]
                rows = con.execute("SELECT * FROM silver_core.crashes ORDER BY collision_id").fetchall()
                vrows = con.execute("SELECT * FROM silver_core.vehicles ORDER BY unique_id").fetchall()
                digest = hashlib.sha256(json.dumps([rows,vrows],default=str).encode()).hexdigest()
                con.execute("COMMIT")
            quality = {"status": "warning" if orphans or missing_location or unknown else "passed",
                       "collisions": totals[0], "injured": totals[1], "killed": totals[2],
                       "involved_vehicles": vehicles, "orphan_vehicles": orphans,
                       "unknown_borough": unknown, "missing_location": missing_location,
                       "quarantined": 0, "observed_extra_fields": additive,
                       "orphan_policy": "retained in core; excluded from joined vehicle aggregates"}
            version = run_id
            serving = data_dir / "published" / f"serving-{version}.duckdb"
            with duckdb.connect(str(candidate), read_only=True) as source_con:
                daily = source_con.execute("SELECT * FROM gold.daily").fetchall()
                vehicle_daily = source_con.execute("SELECT * FROM gold.vehicle_daily").fetchall()
            with duckdb.connect(str(serving)) as output:
                output.execute("CREATE TABLE gold_daily(crash_date DATE,borough VARCHAR,collisions BIGINT,injured BIGINT,killed BIGINT,missing_location BIGINT)")
                output.execute("CREATE TABLE gold_vehicles(crash_date DATE,borough VARCHAR,vehicle_type VARCHAR,involved_vehicles BIGINT)")
                if daily: output.executemany("INSERT INTO gold_daily VALUES (?,?,?,?,?,?)", daily)
                if vehicle_daily: output.executemany("INSERT INTO gold_vehicles VALUES (?,?,?,?)", vehicle_daily)
            manifest = {"version": version, "database": serving.name, "sha256": sha256_file(serving),
                        "schema_version": 1, "generated_at": utc_now(), "source_mode": mode,
                        "data_origin": "synthetic" if mode == "fixture" else "publisher",
                        "window_start": str(horizon), "window_end": str(as_of),
                        "refresh_window_start": str(window_start), "source_max_crash_date": str(maximum),
                        "quality": quality, "content_sha256": digest, "lineage": LINEAGE,
                        "last_full_reconciliation": str(as_of) if window_start == horizon else (previous or {}).get("last_full_reconciliation"),
                        "limitations": ["Reported events, not exposure-adjusted risk", "Corrections outside daily window reconciled weekly"]}
            (data_dir / "transformations.sql").write_text(sql, encoding="utf-8")
            # Two local files form the committed state. Roll back the warehouse
            # if the manifest switch fails, so the next run starts from the same
            # history the API still advertises.
            backup = data_dir / f"warehouse-backup-{run_id}.duckdb"
            had_warehouse = warehouse.exists()
            if had_warehouse:
                os.replace(warehouse, backup)
            try:
                os.replace(candidate, warehouse)
                atomic_json(manifest_path, manifest)
            except Exception:
                if had_warehouse:
                    os.replace(backup, warehouse)
                else:
                    warehouse.unlink(missing_ok=True)
                raise
            finally:
                backup.unlink(missing_ok=True)
            run.update(status="success", finished_at=utc_now(), quality=quality, manifest=manifest,
                       acquisition_start=str(window_start), acquisition_end=str(as_of))
            atomic_json(run_file, run)
            return manifest
    except Exception as exc:
        run.update(status="failed", finished_at=utc_now(), error=f"{type(exc).__name__}: {exc}")
        atomic_json(run_file, run)
        raise
    finally:
        candidate.unlink(missing_ok=True)
