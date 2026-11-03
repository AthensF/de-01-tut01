"""Sixteen executable lessons composing the same production package.

Offline chapters use a synthetic fixture and make no paid inference or deployment
calls. Explicit production commands in the runbook perform external operations.
"""
from __future__ import annotations

import importlib.metadata
import json
import platform
import uuid
from pathlib import Path

from roadsafety.config import atomic_json, sha256_file, utc_now
from roadsafety.fixtures import EXPECTED, fixture_records
from roadsafety.pipeline import QualityError, run_pipeline


def _bootstrap(data_dir: Path, live: bool = False):
    path = data_dir / "published" / "manifest.json"
    if path.exists():
        manifest = json.loads(path.read_text())
        if live and manifest["source_mode"] != "live":
            raise QualityError("Explicit --live lessons require a separate verified live data directory")
        return manifest
    return run_pipeline(data_dir, mode="live" if live else "fixture")


def _schema_incident(data_dir: Path):
    # Fault injection is confined to a separate synthetic lab directory.
    lab = data_dir / "labs" / ("schema-" + uuid.uuid4().hex[:8])
    previous = run_pipeline(lab)
    record = fixture_records()
    record["crashes"][0]["injury_count"] = record["crashes"][0].pop("number_of_persons_injured")
    inputs = lab / "injected-input"
    inputs.mkdir()
    for source in ("crashes", "vehicles", "provenance"):
        atomic_json(inputs / f"{source}.json", record[source])
    try:
        run_pipeline(lab, input_dir=inputs)
    except QualityError as exc:
        from roadsafety.reports import incident
        report = incident(lab)
        retained = json.loads((lab / "published/manifest.json").read_text())["version"] == previous["version"]
        return {"data_origin": "synthetic", "injected_fault": "required-field rename", "error": str(exc),
                "previous_publication_retained": retained, "report": str(report), "lab_dir": str(lab)}
    raise AssertionError("Injected schema fault was not detected")


def capstone(data_dir: Path) -> dict:
    lab = data_dir / "labs" / ("capstone-" + uuid.uuid4().hex[:8])
    before = run_pipeline(lab)
    record = fixture_records()
    # Assessment variant differs from chapter 10's schema rename.
    record["vehicles"].append(record["vehicles"][0].copy())
    inputs = lab / "injected-input"
    inputs.mkdir()
    for source in ("crashes", "vehicles", "provenance"):
        atomic_json(inputs / f"{source}.json", record[source])
    try:
        run_pipeline(lab, input_dir=inputs)
    except QualityError:
        retained = json.loads((lab / "published/manifest.json").read_text())["version"] == before["version"]
    else:
        raise AssertionError("Unseen duplicate-key variant was not detected")
    from roadsafety.reports import incident
    incident_report = incident(lab)
    fixed = run_pipeline(lab, full_reconcile=True)
    from fastapi.testclient import TestClient
    from roadsafety.api import create_app
    with TestClient(create_app(data_dir=lab)) as client:
        response = client.get("/v1/collisions/summary", params={"start_date": "2026-10-29", "end_date": "2026-11-01"})
        response.raise_for_status()
        api_output = response.json()
    assert fixed["quality"]["collisions"] == 6 and fixed["quality"]["injured"] == 3
    outcome = {"data_origin": "synthetic", "assessment": "duplicate vehicle identifier", "publication_preserved": retained,
               "recovered": fixed["quality"]["collisions"] == 6, "analytical_content_restored": fixed["content_sha256"] == before["content_sha256"],
               "api_status": response.status_code, "api": api_output, "incident_report": str(incident_report),
               "lab_dir": str(lab), "review_required": "Review the proposed production fix; this recovery used only a known synthetic fixture."}
    atomic_json(lab / "capstone-result.json", outcome)
    return outcome


def run_lesson(number: int, data_dir: Path = Path("data"), live: bool = False) -> dict:
    data_dir = Path(data_dir)
    if number not in range(1, 17):
        raise ValueError("Chapter must be in 1..16")
    if number == 1:
        if live:
            from roadsafety.ingest import verify_sources
            return verify_sources(data_dir)
        plan = {"status": "unverified", "data_origin": "verification_plan", "checked_at": utc_now(),
                "sources": {"crashes": "h9gi-nx95", "vehicles": "bm4k-52h4"},
                "required_evidence": ["current columns and key uniqueness", "anonymous access", "cadence", "source terms", "revision semantics"],
                "next_command": "python -m roadsafety verify-sources --data-dir live-data",
                "limitation": "This offline plan does not establish live-source readiness."}
        path = data_dir / "reports" / "source-verification-plan.json"
        atomic_json(path, plan)
        return {**plan, "path": str(path)}
    if number == 2:
        return {"python": platform.python_version(), "dependencies": {name: importlib.metadata.version(name) for name in ("duckdb","fastapi","httpx","PyYAML")},
                "data_dir": str(data_dir), "next_command": "python -m roadsafety pipeline --mode fixture"}
    # Acquisition lessons perform exactly one run. Explicit live requests never
    # silently bootstrap fixture records. Fault labs remain isolated synthetic.
    if number in {5, 6}:
        result = run_pipeline(data_dir, mode="live" if live else "fixture")
        return {"chapter": number, "version": result["version"], "quality": result["quality"], "content_sha256": result["content_sha256"]}
    if number == 10:
        return _schema_incident(data_dir)
    if number == 16:
        return capstone(data_dir)
    manifest = _bootstrap(data_dir, live=live)
    from roadsafety import reports
    if number in {3, 4, 7, 10, 11, 12, 15}:
        function = {3: reports.profile, 4: reports.metadata, 7: reports.data_product,
                    11: reports.toolkit, 12: reports.review, 15: reports.platform_review}[number]
        return {"chapter": number, "path": str(function(data_dir)), "source_mode": manifest["source_mode"]}
    if number == 8:
        from fastapi.testclient import TestClient
        from roadsafety.api import create_app
        with TestClient(create_app(data_dir=data_dir)) as client:
            response = client.get("/v1/collisions/summary")
            response.raise_for_status()
            return {"chapter": 8, "api_response": response.json(), "openapi": "/docs", "expected_fixture_totals": EXPECTED if manifest["source_mode"] == "fixture" else None}
    if number == 9:
        return {"chapter": 9, "quality": manifest["quality"], "runs": len(list((data_dir / "runs").glob("*.json"))),
                "publication": manifest["version"], "source_mode": manifest["source_mode"]}
    if number == 13:
        database = data_dir / "published" / manifest["database"]
        assert sha256_file(database) == manifest["sha256"]
        return {"chapter": 13, "local_snapshot_verified": True, "version": manifest["version"],
                "external_deployment": "not performed by this lab", "runbook": "docs/runbook.md"}
    if number == 14:
        from roadsafety.investigation import investigate
        return {"chapter": 14, "investigation": investigate(data_dir, enable_ai=False),
                "hosted_execution": "not performed by this lab", "separate_workflows": ["pipeline.yml", "investigate.yml"]}
    raise AssertionError("Missing chapter dispatcher")
