from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest
import yaml

from roadsafety import reports


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def example(tmp_path):
    raw = tmp_path / "raw" / "001"
    write_json(raw / "crashes.json", [
        {"collision_id": "001", "crash_date": "2026-11-01", "borough": "BRONX", "number_of_persons_injured": "2"},
        {"collision_id": "002", "crash_date": "2026-11-01", "borough": "", "number_of_persons_injured": "1"},
    ])
    write_json(raw / "vehicles.json", [
        {"unique_id": "01", "collision_id": "001", "vehicle_type": "CAR"},
        {"unique_id": "02", "collision_id": "001", "vehicle_type": "BUS"},
        {"unique_id": "03", "collision_id": "999", "vehicle_type": "CAR"},
    ])
    write_json(tmp_path / "published" / "manifest.json", {
        "version": "test-one", "source_mode": "fixture", "schema_version": 1,
        "window_start": "2026-10-01", "window_end": "2026-11-01",
        "quality": {"accepted_crashes": 2},
        "lineage": {"main.gold_daily": ["silver_core.crashes"]},
    })
    with duckdb.connect(str(tmp_path / "warehouse.duckdb")) as connection:
        connection.execute("CREATE SCHEMA silver_core")
        connection.execute("CREATE TABLE silver_core.crashes(collision_id VARCHAR, crash_date DATE, borough VARCHAR, injured BIGINT, killed BIGINT, latitude DOUBLE, longitude DOUBLE, has_location BOOLEAN)")
        connection.execute("INSERT INTO silver_core.crashes VALUES ('001','2026-11-01','BRONX',2,0,40.8,-73.9,true),('002','2026-11-01','UNKNOWN',1,0,NULL,NULL,false)")
        connection.execute("CREATE TABLE silver_core.vehicles(unique_id VARCHAR,collision_id VARCHAR,crash_date DATE,vehicle_type VARCHAR)")
        connection.execute("INSERT INTO silver_core.vehicles VALUES ('01','001','2026-11-01','CAR'),('02','001','2026-11-01','BUS')")
        connection.execute("CREATE TABLE gold_daily AS SELECT crash_date,borough,count(*) AS collisions,sum(injured) AS injured,sum(killed) AS killed,count(*) FILTER(WHERE NOT has_location) AS missing_location FROM silver_core.crashes GROUP BY ALL")
    return tmp_path


def test_profile_computes_real_counts_and_batch_relationships_without_writing_sources(example):
    raw = example / "raw" / "001" / "crashes.json"
    before = hashlib.sha256(raw.read_bytes()).hexdigest()
    output = reports.profile(example)
    facts = json.loads(output.with_suffix(".json").read_text())
    assert facts["tables"]["crashes"]["rows"] == 2
    assert facts["tables"]["crashes"]["candidate_key"]["validated_unique"]
    assert facts["tables"]["crashes"]["column_statistics"]["borough"]["null_or_empty"] == 1
    assert facts["tables"]["crashes"]["identifier_checks"]["leading_zero_records"] == 2
    assert facts["tables"]["crashes"]["dates"]["max_observed_crash_date"] == "2026-11-01"
    assert facts["relationships"]["vehicle_records_without_parent_in_this_batch"] == 1
    assert facts["provenance"]["data_origin"] == "synthetic"
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == before


def test_profile_detects_duplicates_missing_keys_and_schema_changes(example):
    write_json(example / "raw" / "002" / "crashes.json", [{"collision_id": "001", "status": "new"}, {"collision_id": "001", "status": "new"}, {"status": "<script>alert(1)</script>"}])
    write_json(example / "raw" / "002" / "vehicles.json", [])
    output = reports.profile(example)
    facts = json.loads(output.with_suffix(".json").read_text())
    assert facts["tables"]["crashes"]["duplicate_rows"] == 1
    assert facts["tables"]["crashes"]["candidate_key"]["duplicate_records"] == 1
    assert facts["tables"]["crashes"]["candidate_key"]["missing"] == 1
    assert "status" in facts["schema_changes"]["crashes"]["added"]
    assert "crash_date" in facts["schema_changes"]["crashes"]["removed"]


def test_metadata_preserves_identifier_and_requires_documentary_meanings(example):
    write_json(example / "source_documents.json", {"crashes": {
        "collision_id": {"description": "Identifier in the checked teaching contract.", "source": "fixture-contract-v1"},
        "borough": {"description": "Unsupported description without a source"},
    }})
    output = reports.metadata(example)
    metadata = yaml.safe_load(output.read_text())
    columns = {c["name"]: c for c in metadata["sources"]["crashes"]["columns"]}
    assert columns["collision_id"]["observed_json_types"] == ["string"]
    assert columns["collision_id"]["description_source"] == "fixture-contract-v1"
    assert columns["borough"]["description"] == ""
    assert columns["borough"]["description_status"] == "unknown"


def test_profile_flags_invalid_counts_and_numeric_identifier_collision_as_questions(example):
    write_json(example / "raw" / "002" / "crashes.json", [
        {"collision_id": "01", "crash_date": "bad-date", "number_of_persons_injured": "-1"},
        {"collision_id": "1", "crash_date": "2026-11-01", "number_of_persons_injured": "NaN"},
    ])
    write_json(example / "raw" / "002" / "vehicles.json", [])
    facts = json.loads(reports.profile(example).with_suffix(".json").read_text())["tables"]["crashes"]
    assert facts["candidate_key"]["validated_unique"] is True
    assert facts["identifier_checks"]["distinct_keys_collapsing_if_cast_to_integer"] == 1
    assert facts["dates"]["invalid_iso_date_values"] == 1
    assert facts["count_checks"]["number_of_persons_injured"]["negative"] == 1
    assert facts["count_checks"]["number_of_persons_injured"]["not_a_finite_number"] == 1


def test_incident_keeps_reviewed_history_unchanged_and_escapes_inputs(example):
    write_json(example / "runs" / "bad.json", {"run_id": "bad", "status": "failed", "started_at": "2026-11-01T10:00:00Z", "error": "missing required status <script>unsafe</script>"})
    history = example / "knowledge" / "incidents.yaml"
    history.parent.mkdir()
    history.write_text("- incident_id: old\n  diagnosis: required field was removed\n")
    before = history.read_text()
    output = reports.incident(example)
    evidence = json.loads(output.with_suffix(".json").read_text())
    assert evidence["failed_run"]["run_id"] == "bad"
    assert evidence["root_cause_status"].startswith("unconfirmed")
    assert evidence["automatic_fix_or_send"] is False
    assert history.read_text() == before
    assert "<script>unsafe</script>" not in output.read_text()
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in output.read_text()


def test_toolkit_rebuilds_actual_run_history_and_lineage(example):
    index = reports.toolkit(example)
    assert index.exists()
    for name in ["architecture", "lineage", "call-graph", "model", "quality", "catalogue", "runs"]:
        assert (index.parent / f"{name}.html").exists()
    lineage = json.loads((index.parent / "lineage.json").read_text())
    assert lineage["edges"] == [{"downstream": "main.gold_daily", "upstream": "silver_core.crashes"}]
    write_json(example / "runs" / "new.json", {"run_id": "new", "status": "success", "started_at": "2026-11-02T00:00:00Z"})
    reports.toolkit(example)
    assert json.loads((index.parent / "runs.json").read_text())["runs"][0]["run_id"] == "new"
    assert "https://" not in (index.parent / "index.html").read_text()


def test_review_locates_seeded_join_fanout_and_makes_no_code_changes(example):
    output = reports.review(example)
    facts = json.loads(output.with_suffix(".json").read_text())
    finding = facts["findings"][0]
    assert finding["file"] == "sql/unsafe_summary.sql"
    assert finding["line"] == 1
    assert "multiply" in finding["finding"]
    assert facts["verdict"] == "changes_requested"
    assert facts["repository_changes_made"] is False
    assert facts["review_origin"] == "labelled_synthetic_fault_fixture"


def test_data_product_does_not_multiply_crash_measures_by_vehicle_rows(example):
    output = reports.data_product(example)
    product = json.loads(output.with_suffix(".json").read_text())
    assert product["starter_query_result"] == {"collisions": 2, "injured": 3, "killed": 0}
    assert product["consumer_contract"]["version"] == 1
    assert product["provenance"]["data_origin"] == "synthetic"


def test_platform_review_labels_actual_benchmark_and_does_not_claim_disuse(example):
    output = reports.platform_review(example)
    result = json.loads(output.with_suffix(".json").read_text())
    assert result["database_bytes"] > 0
    assert all(row["workload_origin"] == "controlled_benchmark" for row in result["measurements"])
    assert all(row["elapsed_ms"] >= 0 for row in result["measurements"])
    assert result["query_history"] == []
    assert "safe to remove" in result["usage_conclusion"]
