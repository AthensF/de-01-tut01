"""Synthetic transport responses; none of these authorize the real sources."""

import hashlib
import json
import re
from datetime import date

import httpx
import pytest

from roadsafety.ingest import AcquisitionError, SOURCES, acquire_live, verify_sources


def metadata(name, *, terms=True, extra=(), key_type="text"):
    value = {
        "name": f"Synthetic {name}", "attribution": "Synthetic publisher",
        "columns": [
            {"fieldName": field, "dataTypeName": (
                key_type if field == SOURCES[name]["key"] else
                "calendar_date" if field == "crash_date" else
                "number" if field.startswith("number_of_") else "text"
            )}
            for field in (*SOURCES[name]["required"], *extra)
        ],
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


def handler_for(rows=None, *, terms=True, key_type="text"):
    rows = rows or {"crashes": [row("crashes", 1)], "vehicles": [row("vehicles", 1)]}

    def handler(request):
        name = source_name(request.url.path)
        if "/api/views/" in request.url.path:
            return httpx.Response(200, json=metadata(name, terms=terms, key_type=key_type))
        if "$where" not in request.url.params:
            return httpx.Response(200, json=rows[name][:1])
        where = request.url.params.get("$where", "")
        key = SOURCES[name]["key"]
        cursor_match = re.search(rf" AND {key} > (.+)$", where)
        cursor = None
        if cursor_match:
            literal = cursor_match[1]
            if key_type == "text":
                assert re.fullmatch(r"'(?:[^']|'')*'", literal)
                cursor = literal[1:-1].replace("''", "'")
            else:
                assert re.fullmatch(r"-?[0-9]+", literal)
                cursor = int(literal)
        convert = str if key_type == "text" else int
        limit = int(request.url.params["$limit"])
        selected = sorted(rows[name], key=lambda r: convert(r[key]))
        if cursor is not None:
            selected = [r for r in selected if convert(r[key]) > cursor]
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
    queries = []
    base = handler_for(rows, key_type="number")

    def handler(request):
        if "$where" in request.url.params:
            queries.append(request.url.params["$where"])
        return base(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acknowledge(tmp_path, client)
        result = acquire_live(tmp_path, date(2026, 1, 1), date(2026, 1, 10), client, page_size=2)
    assert result["provenance"]["complete"] is True
    assert result["provenance"]["atomic_source_snapshot"] is False
    assert len(result["crashes"]) == len(result["vehicles"]) == 3
    assert "collision_id >" not in queries[0]
    assert queries[1].endswith("collision_id > 3")
    assert [r["collision_id"] for r in result["crashes"]] == ["1", "3", "8"]
    for source in result["provenance"]["sources"].values():
        assert source["complete"] and source["row_count"] == 3
        assert source["key_type"] == "number"
        assert len(source["pages"]) == 2
        for page in source["pages"]:
            assert hashlib.sha256((tmp_path / page["path"]).read_bytes()).hexdigest() == page["sha256"]


def test_text_keyset_paging_preserves_leading_zeros_and_lexical_order(tmp_path):
    keys = ["001", "010", "1", "10", "2"]
    rows = {name: [row(name, key) for key in reversed(keys)] for name in SOURCES}
    queries = []
    base = handler_for(rows)

    def handler(request):
        if "$where" in request.url.params:
            queries.append(request.url.params["$where"])
        return base(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acknowledge(tmp_path, client)
        verification = json.loads((tmp_path / "source_verification.json").read_text())
        result = acquire_live(tmp_path, date(2026, 1, 1), date(2026, 1, 10), client, page_size=2)
    assert "collision_id >" not in queries[0]
    assert queries[1].endswith("collision_id > '010'")
    assert queries[2].endswith("collision_id > '10'")
    for name, spec in SOURCES.items():
        assert [r[spec["key"]] for r in result[name]] == keys
        assert verification["sources"][name]["key_type"] == "text"
        assert verification["sources"][name]["column_types"][spec["key"]] == "text"
        assert result["provenance"]["sources"][name]["key_type"] == "text"
        assert result["provenance"]["sources"][name]["row_count"] == len(keys)


def test_text_cursor_quotes_are_escaped_as_a_single_literal(tmp_path):
    keys = ["a' OR 1=1 --", "b"]
    rows = {name: [row(name, key) for key in keys] for name in SOURCES}
    queries = []
    base = handler_for(rows)

    def handler(request):
        if "$where" in request.url.params:
            queries.append(request.url.params["$where"])
        return base(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acknowledge(tmp_path, client)
        result = acquire_live(tmp_path, date(2026, 1, 1), date(2026, 1, 10), client, page_size=1)
    assert queries[1].endswith("collision_id > 'a'' OR 1=1 --'")
    for name, spec in SOURCES.items():
        assert [r[spec["key"]] for r in result[name]] == keys


@pytest.mark.parametrize("key_type", [None, "calendar_date", "checkbox"])
def test_missing_or_unsupported_key_datatype_cannot_verify(tmp_path, key_type):
    base = handler_for()
    probes = []

    def handler(request):
        if "/api/views/" not in request.url.path:
            probes.append(request)
            return base(request)
        name = source_name(request.url.path)
        value = metadata(name, key_type=key_type)
        if key_type is None:
            for column in value["columns"]:
                if column["fieldName"] == SOURCES[name]["key"]:
                    del column["dataTypeName"]
        return httpx.Response(200, json=value)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = verify_sources(tmp_path, client)
    assert report["status"] == "unverified"
    assert not probes
    for name, spec in SOURCES.items():
        entry = report["sources"][name]
        assert entry["status"] == "unverified"
        assert entry["column_types"][spec["key"]] == key_type
        assert "missing or unsupported datatype" in entry["error"]


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


@pytest.mark.parametrize("key_type", [None, "calendar_date", "number"])
def test_acquisition_rechecks_key_datatype_before_downloading_pages(tmp_path, key_type):
    base = handler_for()
    changed = False
    downloads = []

    def handler(request):
        if changed and "/api/views/" in request.url.path:
            value = metadata(source_name(request.url.path), key_type=key_type)
            return httpx.Response(200, json=value)
        if "$where" in request.url.params:
            downloads.append(request)
        return base(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        acknowledge(tmp_path, client)
        changed = True
        with pytest.raises(AcquisitionError, match="datatype"):
            acquire_live(tmp_path, date(2026, 1, 1), date(2026, 1, 10), client)
    assert not downloads
    manifest_path, = (tmp_path / "landing" / "live").glob("*/manifest.json")
    assert json.loads(manifest_path.read_text())["complete"] is False


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
        path = tmp_path / "source_verification.json"
        receipt = json.loads(path.read_text())
        receipt["terms_review"] = {"source": "synthetic review evidence", "reviewed": True}
        path.write_text(json.dumps(receipt))
        report = verify_sources(tmp_path, client)
        assert report["terms_acknowledged"]
        assert report["terms_review"] == receipt["terms_review"]
        mode = "changed_terms"
        report = verify_sources(tmp_path, client)
    assert report["terms_acknowledged"] is False
    assert "terms_review" not in report


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
