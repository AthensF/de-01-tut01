"""Synthetic transport responses; none of these authorize the real sources."""

import hashlib
import json
from datetime import date

import httpx
import pytest

from roadsafety.ingest import AcquisitionError, SOURCES, acquire_live, verify_sources


def metadata(name, *, terms=True, extra=()):
    value = {
        "name": f"Synthetic {name}", "attribution": "Synthetic publisher",
        "columns": [{"fieldName": field} for field in (*SOURCES[name]["required"], *extra)],
        "metadata": {"custom_fields": {"Update": {"Update Frequency": "Daily"}}},
    }
    if terms:
        value["licenseId"] = "synthetic-test-terms"
    return value


def source_name(path):
    return next(name for name, spec in SOURCES.items() if spec["dataset_id"] in path)


def acknowledge(tmp_path, client):
    report = verify_sources(tmp_path, client)
    assert report["status"] == "verified"
    report["terms_acknowledged"] = True
    (tmp_path / "source_verification.json").write_text(json.dumps(report))


def row(name, key):
    value = {SOURCES[name]["key"]: str(key), "crash_date": "2026-01-05T00:00:00"}
    if name == "vehicles":
        value["collision_id"] = "1"
    return value


def handler_for(rows=None, *, terms=True):
    rows = rows or {"crashes": [row("crashes", 1)], "vehicles": [row("vehicles", 1)]}

    def handler(request):
        name = source_name(request.url.path)
        if "/api/views/" in request.url.path:
            return httpx.Response(200, json=metadata(name, terms=terms))
        if request.url.params.get("$limit") == "1":
            return httpx.Response(200, json=rows[name][:1])
        where = request.url.params.get("$where", "")
        cursor = int(where.rsplit(" > ", 1)[1])
        limit = int(request.url.params["$limit"])
        selected = [r for r in rows[name] if int(r[SOURCES[name]["key"]]) > cursor]
        return httpx.Response(200, json=selected[:limit])

    return handler


def test_verification_does_not_guess_terms(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(handler_for(terms=False))) as client:
        report = verify_sources(tmp_path, client)
    assert report["status"] == "verified"
    assert report["terms_acknowledged"] is False
    assert report["sources"]["crashes"]["terms_status"] == "unresolved"
    assert report["sources"]["crashes"]["terms_evidence"] == {}
    with pytest.raises(AcquisitionError, match="acknowledged"):
        acquire_live(tmp_path, date(2026, 1, 1), date(2026, 1, 10))


def test_verification_preserves_only_publisher_column_descriptions(tmp_path):
    base = handler_for()

    def handler(request):
        if "/api/views/" not in request.url.path:
            return base(request)
        value = metadata(source_name(request.url.path))
        value["columns"][0]["description"] = "Publisher-provided synthetic definition."
        return httpx.Response(200, json=value)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = verify_sources(tmp_path, client)
    entry = report["sources"]["crashes"]
    assert entry["column_descriptions"] == {"collision_id": {
        "description": "Publisher-provided synthetic definition.",
        "source": entry["metadata_url"],
    }}


def test_missing_required_metadata_and_denied_access_remain_unverified(tmp_path):
    def handler(request):
        name = source_name(request.url.path)
        if name == "vehicles":
            return httpx.Response(403)
        value = metadata(name)
        value["columns"] = [{"fieldName": "collision_id"}]
        return httpx.Response(200, json=value)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = verify_sources(tmp_path, client)
    assert report["status"] == "unverified"
    assert all(s["status"] == "unverified" for s in report["sources"].values())
    assert "Required source columns" in report["sources"]["crashes"]["error"]


def test_keyset_paging_and_raw_page_checksums(tmp_path):
    rows = {name: [row(name, key) for key in (1, 3, 8)] for name in SOURCES}
    with httpx.Client(transport=httpx.MockTransport(handler_for(rows))) as client:
        acknowledge(tmp_path, client)
        result = acquire_live(tmp_path, date(2026, 1, 1), date(2026, 1, 10), client, page_size=2)
    assert result["provenance"]["complete"] is True
    assert result["provenance"]["atomic_source_snapshot"] is False
    assert len(result["crashes"]) == len(result["vehicles"]) == 3
    for source in result["provenance"]["sources"].values():
        assert source["complete"] and source["row_count"] == 3
        assert len(source["pages"]) == 2
        for page in source["pages"]:
            assert hashlib.sha256((tmp_path / page["path"]).read_bytes()).hexdigest() == page["sha256"]


def test_retry_after_and_transient_server_error(tmp_path, monkeypatch):
    base = handler_for()
    attempts = 0
    sleeps = []
    monkeypatch.setattr("roadsafety.ingest.time.sleep", sleeps.append)

    def handler(request):
        nonlocal attempts
        if "$where" in request.url.params and "h9gi-nx95" in request.url.path:
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            if attempts == 2:
                return httpx.Response(503)
        return base(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acknowledge(tmp_path, client)
        result = acquire_live(tmp_path, date(2026, 1, 1), date(2026, 1, 10), client)
    assert result["provenance"]["complete"]
    assert attempts == 3 and len(sleeps) == 2


@pytest.mark.parametrize("failure", ["timeout", "duplicate", "max_pages", "outside_window"])
def test_failed_or_inconsistent_pagination_retains_incomplete_evidence(tmp_path, monkeypatch, failure):
    base = handler_for()
    monkeypatch.setattr("roadsafety.ingest.time.sleep", lambda delay: None)

    def handler(request):
        if "$where" not in request.url.params:
            return base(request)
        name = source_name(request.url.path)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if failure == "duplicate":
            return httpx.Response(200, json=[row(name, 1), row(name, 1)])
        if failure == "outside_window":
            invalid = row(name, 1)
            invalid["crash_date"] = "2025-01-01T00:00:00"
            return httpx.Response(200, json=[invalid])
        return httpx.Response(200, json=[row(name, 1), row(name, 2)])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acknowledge(tmp_path, client)
        with pytest.raises(AcquisitionError):
            acquire_live(tmp_path, date(2026, 1, 1), date(2026, 1, 10), client,
                         page_size=2, max_pages=1 if failure == "max_pages" else 5)
    manifests = list((tmp_path / "landing" / "live").glob("*/manifest.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text())["complete"] is False


def test_synthetic_gate_cannot_authorize_live_ingestion(tmp_path):
    (tmp_path / "source_verification.json").write_text(json.dumps({
        "status": "verified", "terms_acknowledged": True, "data_origin": "synthetic",
    }))
    with pytest.raises(AcquisitionError, match="Synthetic"):
        acquire_live(tmp_path, date(2026, 1, 1), date(2026, 1, 10))


def test_acquisition_rechecks_required_metadata(tmp_path):
    base = handler_for()
    changed = False

    def handler(request):
        if changed and "/api/views/" in request.url.path:
            value = metadata(source_name(request.url.path))
            value["columns"] = []
            return httpx.Response(200, json=value)
        return base(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acknowledge(tmp_path, client)
        changed = True
        with pytest.raises(AcquisitionError, match="Required source columns"):
            acquire_live(tmp_path, date(2026, 1, 1), date(2026, 1, 10), client)


def test_additive_columns_preserve_acknowledgment_but_changed_terms_revoke_it(tmp_path):
    base = handler_for()
    mode = "original"

    def handler(request):
        if "/api/views/" not in request.url.path:
            return base(request)
        value = metadata(source_name(request.url.path), extra=("added_optional_field",))
        if mode == "changed_terms":
            value["licenseId"] = "different-synthetic-terms"
        return httpx.Response(200, json=value)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acknowledge(tmp_path, client)
        report = verify_sources(tmp_path, client)
        assert report["terms_acknowledged"]
        mode = "changed_terms"
        report = verify_sources(tmp_path, client)
    assert report["terms_acknowledged"] is False


def test_second_source_failure_cannot_return_a_mixed_success(tmp_path):
    base = handler_for()

    def handler(request):
        if "$where" in request.url.params and "bm4k-52h4" in request.url.path:
            return httpx.Response(403)
        return base(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acknowledge(tmp_path, client)
        with pytest.raises(AcquisitionError, match="incomplete"):
            acquire_live(tmp_path, date(2026, 1, 1), date(2026, 1, 10), client)
    manifest_path, = (tmp_path / "landing" / "live").glob("*/manifest.json")
    manifest = json.loads(manifest_path.read_text())
    assert not manifest["complete"]
    assert manifest["sources"]["crashes"]["complete"]
    assert not manifest["sources"]["vehicles"]["complete"]
