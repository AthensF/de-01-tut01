import json
import threading
from datetime import datetime, timedelta, timezone

import duckdb
import pytest
from fastapi.testclient import TestClient

from roadsafety.api import create_app
from roadsafety.snapshots import checksum


@pytest.fixture
def published(tmp_path):
    folder = tmp_path / "published"
    folder.mkdir()
    path = folder / "serving-test.duckdb"
    with duckdb.connect(str(path)) as db:
        db.execute("CREATE TABLE gold_daily(crash_date DATE, borough VARCHAR, collisions BIGINT, injured BIGINT, killed BIGINT, missing_location BIGINT)")
        db.execute("CREATE TABLE gold_vehicles(crash_date DATE, borough VARCHAR, vehicle_type VARCHAR, involved_vehicles BIGINT)")
        db.execute("INSERT INTO gold_daily VALUES ('2026-10-01','QUEENS',2,3,0,0), ('2026-10-02','UNKNOWN',1,0,1,1), ('2026-10-02','QUEENS',1,1,0,0)")
        db.execute("INSERT INTO gold_vehicles VALUES ('2026-10-01','QUEENS','Sedan',4), ('2026-10-02','UNKNOWN','UNKNOWN',1), ('2026-10-02','QUEENS','Bus',1)")
    manifest = {
        "version": "test", "database": path.name, "sha256": checksum(path), "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(), "source_mode": "fixture",
        "window_start": "2025-01-01", "window_end": "2026-10-02", "source_max_crash_date": "2026-10-02",
        "quality": {"passed": True},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def test_summary_includes_unknown_and_does_not_multiply_crashes(published):
    with TestClient(create_app(published)) as client:
        response = client.get("/v1/collisions/summary")
        assert response.status_code == 200
        body = response.json()
        assert body["totals"] == {"collisions": 4, "injured": 4, "killed": 1, "missing_location": 1}
        assert {row["borough"] for row in body["data"]} == {"QUEENS", "UNKNOWN"}
        assert body["data_version"] == "test"
        assert body["source_mode"] == "fixture"
        assert body["freshness"]["source_max_crash_date"] == "2026-10-02"
        assert client.get("/v1/vehicles/summary").json()["totals"]["involved_vehicles"] == 6
        assert client.get("/v1/collisions/summary?borough=UNKNOWN").json()["totals"]["collisions"] == 1
        assert client.get("/v1/collisions/summary?borough=queens").json()["totals"]["collisions"] == 3


def test_trend_granularity_and_bounded_results(published):
    with TestClient(create_app(published)) as client:
        daily = client.get("/v1/collisions/trends").json()["data"]
        assert [(r["period"], r["collisions"]) for r in daily] == [("2026-10-01", 2), ("2026-10-02", 2)]
        monthly = client.get("/v1/collisions/trends?granularity=month").json()["data"]
        assert len(monthly) == 1 and monthly[0]["collisions"] == 4
        assert len(client.get("/v1/vehicles/summary?limit=1").json()["data"]) == 1
        assert client.get("/v1/vehicles/summary?limit=1").json()["totals"]["involved_vehicles"] == 6


@pytest.mark.parametrize("query", [
    "start_date=2026-10-02&end_date=2026-10-01", "start_date=2025-01-01&end_date=2026-10-01",
    "start_date=invalid", "end_date=2027-01-01", "start_date=2024-01-01&end_date=2024-01-02",
    "borough=QUEENS%27%20OR%201=1--", "borough=missing", "limit=1001", "limit=0",
    "granularity=year",
])
def test_invalid_queries_are_rejected(published, query):
    with TestClient(create_app(published)) as client:
        assert client.get("/v1/collisions/trends?" + query).status_code == 422


def test_missing_snapshot_and_docs(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/health").status_code == 503
        assert client.get("/ready").status_code == 503
        for route in ["/v1/collisions/summary", "/v1/collisions/trends", "/v1/vehicles/summary", "/v1/data-status"]:
            assert client.get(route).status_code == 503
        assert client.get("/docs").status_code == 200


def test_stale_snapshot_is_served_with_degraded_health(published):
    path = published / "published" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["generated_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    path.write_text(json.dumps(manifest))
    with TestClient(create_app(published)) as client:
        assert client.get("/health").status_code == 503
        assert client.get("/ready").status_code == 200
        result = client.get("/v1/collisions/summary")
        assert result.status_code == 200
        assert result.json()["freshness"]["stale"]


def test_latest_failed_attempt_degrades_health_without_hiding_data(published):
    runs = published / "runs"
    runs.mkdir()
    (runs / "latest.json").write_text(json.dumps({"run_id": "failed-run", "status": "failed", "private_details": "not-public"}))
    with TestClient(create_app(published)) as client:
        assert client.get("/health").status_code == 503
        assert client.get("/ready").status_code == 200
        status = client.get("/v1/data-status").json()
        assert status["latest_attempt"] == {"run_id": "failed-run", "status": "failed"}
        assert client.get("/v1/collisions/summary").status_code == 200


def test_warm_update_retains_good_version_on_invalid_manifest(published):
    app = create_app(published)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        path = published / "published" / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["version"] = "new"
        path.write_text(json.dumps(manifest))
        assert app.state.snapshot_store.refresh()
        assert client.get("/v1/collisions/summary").json()["data_version"] == "new"
        path.write_text("not JSON")
        assert not app.state.snapshot_store.refresh()
        assert client.get("/v1/collisions/summary").json()["data_version"] == "new"
        assert client.get("/health").status_code == 503
        assert client.get("/ready").status_code == 200


def test_unreadable_database_fails_readiness(published):
    with TestClient(create_app(published)) as client:
        assert client.get("/ready").status_code == 200
        (published / "published" / "serving-test.duckdb").unlink()
        assert client.get("/ready").status_code == 503
        assert client.get("/health").status_code == 503


def test_periodic_refresh_discovers_new_snapshot(published, monkeypatch):
    app = create_app(published, refresh_seconds=1)
    store = app.state.snapshot_store
    original_refresh = store.refresh
    updated = threading.Event()

    def observed_refresh():
        outcome = original_refresh()
        if store.get() and store.get().manifest["version"] == "periodic":
            updated.set()
        return outcome

    monkeypatch.setattr(store, "refresh", observed_refresh)
    with TestClient(app) as client:
        path = published / "published" / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["version"] = "periodic"
        path.write_text(json.dumps(manifest))
        assert updated.wait(timeout=4), "background refresh did not install the publication"
        assert client.get("/v1/data-status").json()["data_version"] == "periodic"
