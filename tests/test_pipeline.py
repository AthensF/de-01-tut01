import json
from datetime import date

import duckdb
import pytest

from roadsafety.config import months_before
from roadsafety.fixtures import fixture_records
from roadsafety.pipeline import QualityError, run_pipeline


def inputs(path, records):
    path.mkdir(exist_ok=True)
    for name in ("crashes", "vehicles", "provenance"):
        (path / f"{name}.json").write_text(json.dumps(records[name]))
    return path


def test_fixture_totals_unknowns_and_idempotent_keys(tmp_path):
    first = run_pipeline(tmp_path)
    second = run_pipeline(tmp_path)
    assert first["content_sha256"] == second["content_sha256"]
    assert second["source_mode"] == "fixture"
    assert second["data_origin"] == "synthetic"
    q = second["quality"]
    assert (q["collisions"], q["injured"], q["killed"], q["involved_vehicles"]) == (6, 3, 1, 6)
    assert (q["unknown_borough"], q["missing_location"]) == (1, 2)
    with duckdb.connect(str(tmp_path / "warehouse.duckdb"), read_only=True) as con:
        assert con.execute("SELECT COUNT(DISTINCT collision_id) FROM silver_core.crashes").fetchone()[0] == 6
        # Two vehicles for crash 001 must not multiply its two injuries.
        assert con.execute("SELECT SUM(injured) FROM gold.daily").fetchone()[0] == 3
        assert con.execute("SELECT SUM(involved_vehicles) FROM gold.vehicle_daily").fetchone()[0] == 6


@pytest.mark.parametrize("fault", ["rename", "duplicate", "negative", "partial", "invalid_date"])
def test_bad_batch_preserves_publication(tmp_path, fault):
    data = tmp_path / "data"
    previous = run_pipeline(data)
    before = (data / "published/manifest.json").read_bytes()
    rows = fixture_records()
    if fault == "rename": rows["crashes"][0]["injury_count"] = rows["crashes"][0].pop("number_of_persons_injured")
    if fault == "duplicate": rows["crashes"].append(rows["crashes"][0].copy())
    if fault == "negative": rows["crashes"][0]["number_of_persons_injured"] = "-1"
    if fault == "partial": rows["provenance"]["complete"] = False
    if fault == "invalid_date": rows["crashes"][0]["crash_date"] = "not-a-date"
    with pytest.raises(QualityError):
        run_pipeline(data, input_dir=inputs(tmp_path / "input", rows))
    assert (data / "published/manifest.json").read_bytes() == before
    runs = [json.loads(p.read_text()) for p in (data / "runs").glob("*.json")]
    assert any(r["status"] == "failed" for r in runs)
    assert previous["quality"]["injured"] == 3


def test_old_correction_and_deletion_wait_for_full_reconciliation(tmp_path):
    records = fixture_records()
    old = records["crashes"][0].copy()
    old.update(collision_id="OLD", crash_date="2025-02-01", number_of_persons_injured="5")
    records["crashes"].append(old)
    input_dir = inputs(tmp_path / "input", records)
    data = tmp_path / "data"
    run_pipeline(data, input_dir=input_dir)
    records["crashes"][-1]["number_of_persons_injured"] = "7"
    inputs(input_dir, records)
    daily = run_pipeline(data, input_dir=input_dir)
    assert daily["quality"]["injured"] == 8  # retained old value (5) + recent (3)
    full = run_pipeline(data, input_dir=input_dir, full_reconcile=True)
    assert full["quality"]["injured"] == 10
    records["crashes"].pop()
    inputs(input_dir, records)
    removed = run_pipeline(data, input_dir=input_dir, full_reconcile=True)
    assert removed["quality"]["injured"] == 3
    assert removed["quality"]["collisions"] == 6


def test_additive_field_and_identifier_preservation(tmp_path):
    records = fixture_records()
    records["crashes"][0]["future_attribute"] = "new"
    result = run_pipeline(tmp_path / "data", input_dir=inputs(tmp_path / "input", records))
    assert "future_attribute" in result["quality"]["observed_extra_fields"]["crashes"]
    with duckdb.connect(str(tmp_path / "data/warehouse.duckdb"), read_only=True) as con:
        assert con.execute("SELECT collision_id FROM silver_core.crashes ORDER BY collision_id LIMIT 1").fetchone()[0] == "001"


def test_no_older_or_mixed_mode_publication(tmp_path):
    run_pipeline(tmp_path)
    with pytest.raises(QualityError, match="newer publication"):
        run_pipeline(tmp_path, as_of=date(2026, 10, 31))
    with pytest.raises(QualityError, match="separate data directories"):
        run_pipeline(tmp_path, mode="live")


def test_calendar_retention_leap_day():
    assert months_before(date(2024, 2, 29), 24) == date(2022, 2, 28)


def test_manifest_write_failure_rolls_back_internal_history(tmp_path, monkeypatch):
    from roadsafety import pipeline
    data = tmp_path / "data"
    previous = run_pipeline(data)
    rows = fixture_records()
    rows["crashes"][0]["number_of_persons_injured"] = "9"
    source = inputs(tmp_path / "inputs", rows)
    original = pipeline.atomic_json
    def failing_write(path, value):
        if path == data / "published/manifest.json":
            raise OSError("simulated manifest switch failure")
        return original(path, value)
    monkeypatch.setattr(pipeline, "atomic_json", failing_write)
    with pytest.raises(OSError, match="manifest switch"):
        run_pipeline(data, input_dir=source)
    assert json.loads((data / "published/manifest.json").read_text())["version"] == previous["version"]
    with duckdb.connect(str(data / "warehouse.duckdb"), read_only=True) as con:
        assert con.execute("SELECT SUM(injured) FROM silver_core.crashes").fetchone()[0] == 3
