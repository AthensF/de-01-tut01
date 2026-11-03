from __future__ import annotations

import hashlib
import io
import json
import os
import random
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import duckdb

from roadsafety.deploy import persist_operations, publish, restore_state
from roadsafety.investigation import investigate
from roadsafety.snapshots import TABLE_COLUMNS


NOW = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)


def write_run(tmp_path, run_id="run-1", status="failed", started_at=None):
    path = tmp_path / "runs" / f"{run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_id": run_id, "status": status, "source_mode": "fixture",
                                "started_at": (started_at or NOW).isoformat(),
                                "finished_at": (started_at or NOW).isoformat(),
                                "error": {"type": "SchemaError", "message": "collision_id missing"}}))


def model_client(handler=None):
    calls = []

    def respond(request):
        calls.append(request)
        if handler:
            return handler(request)
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "Observed missing collision_id; review the source contract."}]}],
            "usage": {"input_tokens": 400, "output_tokens": 80}})

    return httpx.Client(transport=httpx.MockTransport(respond)), calls


def test_offline_report_requires_no_model_or_secret(tmp_path):
    write_run(tmp_path)
    report = investigate(tmp_path, now=NOW)
    assert report["ai_status"] == "disabled"
    assert "collision_id" in report["evidence"]
    assert report["recommended_checks"]
    assert (tmp_path / "investigations/latest.json").is_file()
    assert not (tmp_path / "investigations/budget.json").exists()


def test_successful_run_does_not_call_model(tmp_path):
    write_run(tmp_path, status="success")
    client, calls = model_client()
    assert investigate(tmp_path, now=NOW, enable_ai=True, api_key="test-key", client=client)["ai_status"] == "not_needed"
    assert not calls


def test_budget_exhaustion_refuses_model(tmp_path):
    write_run(tmp_path)
    ledger = tmp_path / "investigations/budget.json"
    ledger.parent.mkdir()
    ledger.write_text(json.dumps({"schema_version": 1, "entries": [
        {"run_id": "older", "day": "2026-11-01", "month": "2026-11", "charged_usd": "4.95"}]}))
    client, calls = model_client()
    result = investigate(tmp_path, now=NOW, enable_ai=True, api_key="test-key", client=client)
    assert result["ai_status"] == "budget_exhausted"
    assert not calls
    assert len(json.loads(ledger.read_text())["entries"]) == 1


def test_missing_run_evidence_is_unavailable(tmp_path):
    report = investigate(tmp_path, now=NOW)
    assert report["ai_status"] == "unavailable"
    assert report["evidence_status"] == "missing"


@pytest.mark.parametrize("status", ["running", "unknown"])
def test_incomplete_run_is_unavailable(tmp_path, status):
    write_run(tmp_path, status=status)
    report = investigate(tmp_path, now=NOW)
    assert report["ai_status"] == "unavailable"
    assert report["evidence_status"] == "incomplete"


def test_completed_status_without_completion_evidence_is_unavailable(tmp_path):
    write_run(tmp_path, status="success")
    path = tmp_path / "runs/run-1.json"
    run = json.loads(path.read_text())
    del run["finished_at"]
    path.write_text(json.dumps(run))
    assert investigate(tmp_path, now=NOW)["evidence_status"] == "incomplete"


def test_stale_success_does_not_claim_no_investigation_needed(tmp_path):
    write_run(tmp_path, status="success", started_at=NOW - timedelta(days=2))
    report = investigate(tmp_path, now=NOW)
    assert report["ai_status"] == "unavailable"
    assert report["evidence_status"] == "stale"


def test_recent_failure_is_investigated_despite_newer_success(tmp_path):
    write_run(tmp_path, "failed", started_at=NOW - timedelta(hours=2))
    write_run(tmp_path, "recovered", status="success", started_at=NOW)
    client, calls = model_client()
    report = investigate(tmp_path, now=NOW, enable_ai=True, api_key="test-key", client=client)
    assert report["ai_status"] == "completed"
    assert report["run_id"] == "failed"
    assert report["latest_pipeline_status"] == "success"
    evidence = json.loads(json.loads(calls[0].content)["input"])
    assert evidence["later_pipeline_run"]["run_id"] == "recovered"


def test_credential_refusal_leaves_failure_eligible(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    write_run(tmp_path)
    assert investigate(tmp_path, now=NOW, enable_ai=True)["ai_status"] == "unavailable"
    assert not (tmp_path / "investigations/budget.json").exists()
    client, calls = model_client()
    assert investigate(tmp_path, now=NOW, enable_ai=True, api_key="test-key", client=client)["ai_status"] == "completed"
    assert len(calls) == 1


def test_failures_older_than_a_week_are_not_selected(tmp_path):
    write_run(tmp_path, "old", started_at=NOW - timedelta(days=8))
    write_run(tmp_path, "current", status="success", started_at=NOW)
    assert investigate(tmp_path, now=NOW)["ai_status"] == "not_needed"


def test_success_reserves_before_call_and_deduplicates(tmp_path):
    write_run(tmp_path)
    events = []

    def response(request):
        assert events == ["persist"]
        budget = json.loads((tmp_path / "investigations/budget.json").read_text())
        assert budget["entries"][0]["status"] == "reserved"
        body = json.loads(request.content)
        assert body["max_output_tokens"] == 1000
        assert body["store"] is False
        assert "tools" not in body
        events.append("model")
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "Review the schema evidence."}]}],
            "usage": {"input_tokens": 100, "output_tokens": 20}})

    client, calls = model_client(response)
    result = investigate(tmp_path, now=NOW, enable_ai=True, api_key="test-key", client=client,
                         persist_ledger=lambda: events.append("persist"))
    assert result["ai_status"] == "completed"
    assert events == ["persist", "model", "persist"]
    second = investigate(tmp_path, now=NOW + timedelta(days=1), enable_ai=True, api_key="test-key", client=client)
    assert second["ai_status"] == "deduplicated"
    assert len(calls) == 1


def test_daily_limit_even_for_different_failure(tmp_path):
    write_run(tmp_path)
    client, calls = model_client()
    investigate(tmp_path, now=NOW, enable_ai=True, api_key="test-key", client=client)
    write_run(tmp_path, "run-2", started_at=NOW + timedelta(minutes=1))
    result = investigate(tmp_path, now=NOW + timedelta(minutes=2), enable_ai=True, api_key="test-key", client=client)
    assert result["ai_status"] == "daily_limit"
    assert len(calls) == 1


def test_model_error_retains_reservation(tmp_path):
    write_run(tmp_path)
    client, calls = model_client(lambda request: httpx.Response(500))
    result = investigate(tmp_path, now=NOW, enable_ai=True, api_key="test-key", client=client)
    assert result["ai_status"] == "unavailable"
    entry = json.loads((tmp_path / "investigations/budget.json").read_text())["entries"][0]
    assert entry["status"] == "uncertain"
    assert entry["charged_usd"] == "0.10"
    assert len(calls) == 1


def test_failed_remote_reservation_prevents_paid_call(tmp_path):
    write_run(tmp_path)
    client, calls = model_client()

    def fail_persistence():
        raise OSError("offline")

    result = investigate(tmp_path, now=NOW, enable_ai=True, api_key="test-key", client=client,
                         persist_ledger=fail_persistence)
    assert result["ai_status"] == "unavailable"
    assert "not called" in result["reason"]
    assert not calls


def test_large_failure_evidence_is_bounded(tmp_path):
    write_run(tmp_path)
    run_path = tmp_path / "runs/run-1.json"
    run = json.loads(run_path.read_text())
    run["error"] = "é" * 100_000
    run_path.write_text(json.dumps(run))
    report = investigate(tmp_path, now=NOW)
    assert len(report["evidence"].encode()) <= 12_000


def test_corrupt_negative_budget_refuses_paid_call(tmp_path):
    write_run(tmp_path)
    ledger = tmp_path / "investigations/budget.json"
    ledger.parent.mkdir()
    ledger.write_text(json.dumps({"schema_version": 1, "entries": [
        {"run_id": "older", "day": "2026-11-01", "month": "2026-11", "charged_usd": "-10"}]}))
    client, calls = model_client()
    report = investigate(tmp_path, now=NOW, enable_ai=True, api_key="test-key", client=client)
    assert report["ai_status"] == "unavailable"
    assert not calls


def publication_fixture(tmp_path):
    directory = tmp_path / "published"
    directory.mkdir()
    database = directory / "serving-version1.duckdb"
    with duckdb.connect(str(database)) as connection:
        for table, columns in TABLE_COLUMNS.items():
            connection.execute(f"CREATE TABLE {table} (" + ", ".join(f"{name} {kind}" for name, kind in columns.items()) + ")")
    manifest = {"version": "version1", "database": database.name, "schema_version": 1,
                "source_mode": "live", "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
                "generated_at": NOW.isoformat(), "window_start": "2024-11-03", "window_end": "2026-11-03",
                "source_max_crash_date": None, "quality": {"passed": True}}
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def publication_transport(*, fail_database=False):
    events = []
    uploaded = {}

    def respond(request):
        if request.method == "GET" and "/tags/" in request.url.path:
            return httpx.Response(404)
        if request.method == "POST" and request.url.path.endswith("/releases"):
            events.append("create-draft")
            assert json.loads(request.content)["draft"] is True
            return httpx.Response(201, json={"id": 1, "draft": True,
                "upload_url": "https://uploads.github.com/repos/owner/repo/releases/1/assets{?name,label}"})
        if request.method == "GET" and request.url.path.endswith("/assets"):
            return httpx.Response(200, json=[])
        if request.method == "POST" and request.url.host == "uploads.github.com":
            name = request.url.params["name"]
            events.append(name)
            uploaded[name] = request.content
            if fail_database and name.endswith(".duckdb"):
                return httpx.Response(500)
            return httpx.Response(201, json={"id": 10, "state": "uploaded"})
        if request.method == "PATCH":
            events.append("publish-latest")
            assert json.loads(request.content) == {"draft": False, "make_latest": "true"}
            return httpx.Response(200, json={"html_url": "https://github.com/owner/repo/releases/tag/data-version1"})
        raise AssertionError((request.method, str(request.url)))

    return httpx.Client(transport=httpx.MockTransport(respond)), events, uploaded


def test_publication_uploads_manifest_last_and_uses_immutable_database_url(tmp_path):
    manifest = publication_fixture(tmp_path)
    client, events, uploaded = publication_transport()
    result = publish(tmp_path, repository="owner/repo", token="test-token", client=client)
    assert result["status"] == "published"
    assert events == ["create-draft", manifest["database"], "manifest.json", "publish-latest"]
    remote = json.loads(uploaded["manifest.json"])
    assert remote["database_url"] == "https://github.com/owner/repo/releases/download/data-version1/serving-version1.duckdb"
    assert "database_url" not in json.loads((tmp_path / "published/manifest.json").read_text())


def test_failed_asset_upload_does_not_replace_latest_and_records_failure(tmp_path):
    publication_fixture(tmp_path)
    client, events, _ = publication_transport(fail_database=True)
    with pytest.raises(httpx.HTTPStatusError):
        publish(tmp_path, repository="owner/repo", token="test-token", client=client)
    assert "manifest.json" not in events
    assert "publish-latest" not in events
    failure = json.loads(next((tmp_path / "runs").glob("*.json")).read_text())
    assert failure["status"] == "failed"
    assert failure["error"]["stage"] == "publication"


def test_fixture_publication_is_rejected_without_network(tmp_path):
    publication_fixture(tmp_path)
    manifest_path = tmp_path / "published/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["source_mode"] = "fixture"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="live"):
        publish(tmp_path, repository="owner/repo", token="test-token")


def test_state_archive_round_trip_and_preserves_failed_evidence(tmp_path):
    source = tmp_path / "source"
    write_run(source)
    (source / "warehouse.duckdb").write_bytes(b"warehouse")
    (source / "warehouse.duckdb.wal").write_bytes(b"not-a-consistent-checkpoint")
    (source / "published").mkdir()
    (source / "published/manifest.json").write_text('{"version":"previous"}')
    (source / "published/old-serving.duckdb").write_bytes(b"excluded serving snapshot")
    (source / "transformations.sql").write_text("select 1;")
    landing = source / "landing/live/acquisition-1"
    landing.mkdir(parents=True)
    original_bytes = b'[{"collision_id":"1", "borough":null}]\n'
    (landing / "crashes-0001.json").write_bytes(original_bytes)
    (landing / "manifest.json").write_text('{"origin":"live"}')
    stored = {}
    assets = []
    release = {"id": 2, "upload_url": "https://uploads.github.com/repos/owner/repo/releases/2/assets{?name,label}"}

    def respond(request):
        if "/tags/" in request.url.path:
            return httpx.Response(200, json=release)
        if request.method == "POST":
            name = request.url.params["name"]
            stored[name] = request.content
            assets.append({"id": 3, "name": name, "state": "uploaded",
                           "url": "https://api.github.com/repos/owner/repo/releases/assets/3",
                           "digest": "sha256:" + hashlib.sha256(request.content).hexdigest()})
            return httpx.Response(201, json=assets[-1])
        if request.url.path.endswith("/assets"):
            return httpx.Response(200, json=assets)
        if request.url.path.endswith("/assets/3"):
            return httpx.Response(200, content=next(iter(stored.values())))
        raise AssertionError(str(request.url))

    client = httpx.Client(transport=httpx.MockTransport(respond))
    persist_operations(source, repository="owner/repo", token="test-token", client=client)
    target = tmp_path / "restored"
    assert restore_state(target, repository="owner/repo", token="test-token", client=client)
    assert (target / "warehouse.duckdb").read_bytes() == b"warehouse"
    assert json.loads((target / "runs/run-1.json").read_text())["status"] == "failed"
    assert json.loads((target / "published/manifest.json").read_text())["version"] == "previous"
    assert not (target / "published/old-serving.duckdb").exists()
    assert (target / "transformations.sql").read_text() == "select 1;"
    assert (target / "landing/live/acquisition-1/crashes-0001.json").read_bytes() == original_bytes
    assert not (target / "warehouse.duckdb.wal").exists()
    with pytest.raises(ValueError, match="empty"):
        restore_state(target, repository="owner/repo", token="test-token", client=client)


def test_restore_rejects_path_traversal(tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo("../escape")
        member.size = 4
        archive.addfile(member, io.BytesIO(b"evil"))

    def respond(request):
        if "/tags/" in request.url.path:
            return httpx.Response(200, json={"id": 2})
        if request.url.path.endswith("/assets"):
            return httpx.Response(200, json=[{"id": 3, "name": "state-current.tar.gz", "state": "uploaded",
                "url": "https://api.github.com/repos/owner/repo/releases/assets/3"}])
        return httpx.Response(200, content=buffer.getvalue())

    with pytest.raises(ValueError, match="Unsafe"):
        restore_state(tmp_path / "data", repository="owner/repo", client=httpx.Client(transport=httpx.MockTransport(respond)))
    assert not (tmp_path / "escape").exists()


class ArchiveService:
    def __init__(self, fail_evidence=False):
        self.releases = {}
        self.assets = {}
        self.events = []
        self.fail_evidence = fail_evidence
        self.client = httpx.Client(transport=httpx.MockTransport(self.respond))

    def respond(self, request):
        path = request.url.path
        if request.method == "GET" and "/releases/tags/" in path:
            release = self.releases.get(path.split("/tags/")[1])
            return httpx.Response(200, json=release) if release else httpx.Response(404)
        if request.method == "POST" and path.endswith("/releases"):
            body = json.loads(request.content)
            assert body["prerelease"] is True and body["make_latest"] == "false"
            identifier = len(self.releases) + 1
            release = {"id": identifier, "tag_name": body["tag_name"],
                       "upload_url": f"https://uploads.github.com/repos/owner/repo/releases/{identifier}/assets"}
            self.releases[body["tag_name"]] = release
            return httpx.Response(201, json=release)
        if request.method == "POST" and request.url.host == "uploads.github.com":
            name = request.url.params["name"]
            self.events.append(name)
            if self.fail_evidence and name.startswith("evidence-"):
                return httpx.Response(500)
            identifier = len(self.assets) + 1
            asset = {"id": identifier, "name": name, "state": "uploaded", "release_id": int(path.split("/")[-2]),
                     "digest": "sha256:" + hashlib.sha256(request.content).hexdigest(),
                     "url": f"https://api.github.com/repos/owner/repo/releases/assets/{identifier}"}
            self.assets[identifier] = (asset, request.content)
            return httpx.Response(201, json=asset)
        if request.method == "GET" and path.endswith("/assets"):
            identifier = int(path.split("/")[-2])
            return httpx.Response(200, json=[asset for asset, body in self.assets.values() if asset["release_id"] == identifier])
        if request.method == "GET" and "/releases/assets/" in path:
            asset, body = self.assets[int(path.split("/")[-1])]
            return httpx.Response(200, content=body)
        raise AssertionError((request.method, str(request.url)))


def make_raw_batches(data_dir):
    originals = {}
    for index in range(4):
        for kind in ("raw", "landing/live"):
            relative = f"{kind}/batch-{index}/original-response.bin"
            path = data_dir / relative
            path.parent.mkdir(parents=True)
            content = random.Random(index).randbytes(64_000)
            path.write_bytes(content)
            os.utime(path, (NOW.timestamp() + index, NOW.timestamp() + index))
            originals[relative] = content
    return originals


def test_old_raw_bytes_remain_reachable_and_recovery_bundle_is_bounded(tmp_path):
    source = tmp_path / "source"
    originals = make_raw_batches(source)
    service = ArchiveService()
    result = persist_operations(source, repository="owner/repo", token="test-token", client=service.client)
    assert result["archived_evidence_batches"] == 4
    index = json.loads((source / "evidence-index.json").read_text())
    assert len(index["archives"]) == 4
    for entry in index["archives"]:
        asset, body = service.assets[entry["asset_id"]]
        assert hashlib.sha256(body).hexdigest() == entry["sha256"]
        assert entry["download_url"].endswith(asset["name"])
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
            for member in archive.getmembers():
                assert archive.extractfile(member).read() == originals[member.name]
    state_body = next(body for asset, body in service.assets.values() if asset["name"].startswith("state-"))
    assert len(state_body) < sum(map(len, originals.values())) * 0.75
    assert service.events[-1].startswith("state-")
    restored = tmp_path / "restored"
    assert restore_state(restored, repository="owner/repo", token="test-token", client=service.client)
    assert json.loads((restored / "evidence-index.json").read_text()) == index
    for relative, content in originals.items():
        assert (source / relative).read_bytes() == content  # No local evidence deleted.
        if "batch-0" in relative or "batch-1" in relative:
            assert not (restored / relative).exists()
        else:
            assert (restored / relative).read_bytes() == content
    evidence_count = len(index["archives"])
    persist_operations(source, repository="owner/repo", token="test-token", client=service.client)
    assert len(json.loads((source / "evidence-index.json").read_text())["archives"]) == evidence_count


def test_failed_evidence_upload_cannot_create_incomplete_recovery_bundle(tmp_path):
    source = tmp_path / "source"
    originals = make_raw_batches(source)
    service = ArchiveService(fail_evidence=True)
    with pytest.raises(httpx.HTTPStatusError):
        persist_operations(source, repository="owner/repo", token="test-token", client=service.client)
    assert not any(name.startswith("state-") for name in service.events)
    assert not (source / "evidence-index.json").exists()
    for relative, content in originals.items():
        assert (source / relative).read_bytes() == content
