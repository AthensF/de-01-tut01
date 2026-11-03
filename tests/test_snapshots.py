import io
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

from roadsafety import snapshots
from roadsafety.snapshots import SnapshotError, SnapshotStore, checksum, validate_manifest


def publish(data_dir: Path, version="one", collisions=2, **changes):
    published = data_dir / "published"
    published.mkdir(parents=True, exist_ok=True)
    database = published / f"serving-{version}.duckdb"
    with duckdb.connect(str(database)) as db:
        db.execute("CREATE TABLE gold_daily(crash_date DATE, borough VARCHAR, collisions BIGINT, injured BIGINT, killed BIGINT, missing_location BIGINT)")
        db.execute("CREATE TABLE gold_vehicles(crash_date DATE, borough VARCHAR, vehicle_type VARCHAR, involved_vehicles BIGINT)")
        db.execute("INSERT INTO gold_daily VALUES ('2026-10-01','QUEENS',?,1,0,0)", [collisions])
        db.execute("INSERT INTO gold_vehicles VALUES ('2026-10-01','QUEENS','Sedan',3)")
    manifest = {
        "version": version, "database": database.name, "sha256": checksum(database),
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_mode": "fixture", "window_start": "2026-10-01", "window_end": "2026-10-31",
        "source_max_crash_date": "2026-10-01", "quality": {"passed": True}, **changes,
    }
    (published / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def test_empty_store_reports_unavailable(tmp_path):
    store = SnapshotStore(tmp_path)
    assert not store.refresh()
    assert store.get() is None
    assert store.last_error


def test_refresh_switches_version_and_preserves_active_reader(tmp_path):
    publish(tmp_path)
    store = SnapshotStore(tmp_path)
    assert store.refresh()
    original = store.get()
    publish(tmp_path, "two", collisions=9)
    assert store.refresh()
    assert store.get().manifest["version"] == "two"
    with duckdb.connect(str(original.database), read_only=True) as db:
        assert db.execute("SELECT collisions FROM gold_daily").fetchone()[0] == 2


def test_corrupt_publication_retains_good_snapshot_on_refresh_and_restart(tmp_path):
    publish(tmp_path)
    store = SnapshotStore(tmp_path)
    assert store.refresh()
    broken = publish(tmp_path, "broken")
    (tmp_path / "published" / broken["database"]).write_bytes(b"corrupt")
    assert not store.refresh()
    assert store.get().manifest["version"] == "one"
    restarted = SnapshotStore(tmp_path)
    assert not restarted.refresh()
    assert restarted.get().manifest["version"] == "one"
    assert "checksum" in restarted.last_error


@pytest.mark.parametrize("changes", [
    {"database": "../escape.duckdb"}, {"database": "/tmp/escape.duckdb"},
    {"database": "folder\\escape.duckdb"}, {"schema_version": 2},
    {"version": "../bad"}, {"sha256": "bad"}, {"source_mode": "invented"},
    {"generated_at": "2026-10-01T00:00:00"}, {"window_start": "20261001"},
])
def test_manifest_rejects_invalid_contract(tmp_path, changes):
    manifest = publish(tmp_path)
    with pytest.raises(SnapshotError):
        validate_manifest({**manifest, **changes})


def test_database_schema_and_symlink_are_checked(tmp_path):
    manifest = publish(tmp_path)
    path = tmp_path / "published" / manifest["database"]
    with duckdb.connect(str(path)) as db:
        db.execute("DROP TABLE gold_vehicles")
    manifest["sha256"] = checksum(path)
    (tmp_path / "published" / "manifest.json").write_text(json.dumps(manifest))
    store = SnapshotStore(tmp_path)
    assert not store.refresh()
    assert store.get() is None
    target = tmp_path / "outside.duckdb"
    path.rename(target)
    path.symlink_to(target)
    assert not store.refresh()
    assert "escapes" in store.last_error


def test_snapshot_cannot_replace_a_serving_table_with_a_view(tmp_path):
    manifest = publish(tmp_path)
    path = tmp_path / "published" / manifest["database"]
    with duckdb.connect(str(path)) as db:
        db.execute("ALTER TABLE gold_daily RENAME TO backing")
        db.execute("CREATE VIEW gold_daily AS SELECT * FROM backing")
    manifest["sha256"] = checksum(path)
    (tmp_path / "published" / "manifest.json").write_text(json.dumps(manifest))
    store = SnapshotStore(tmp_path)
    assert not store.refresh()
    assert "stored table" in store.last_error


def test_existing_version_cannot_change(tmp_path):
    manifest = publish(tmp_path)
    store = SnapshotStore(tmp_path)
    assert store.refresh()
    manifest["quality"] = {"passed": False}
    (tmp_path / "published" / "manifest.json").write_text(json.dumps(manifest))
    assert not store.refresh()
    assert store.get().manifest["quality"] == {"passed": True}


def test_remote_download_is_verified_atomic_and_restartable(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    manifest = publish(remote)
    url = "https://example.com/release/manifest.json"
    bodies = {url: json.dumps(manifest).encode(),
              "https://example.com/release/" + manifest["database"]: (remote / "published" / manifest["database"]).read_bytes()}
    monkeypatch.setattr(snapshots, "_open_url", lambda address: io.BytesIO(bodies[address]))
    local = tmp_path / "local"
    store = SnapshotStore(local, url)
    assert store.refresh()
    assert store.get().manifest["version"] == "one"
    assert (local / "published" / "manifest.json").is_file()
    assert SnapshotStore(local).refresh()
    bad = publish(remote, "two")
    bodies[url] = json.dumps(bad).encode()
    bodies["https://example.com/release/" + bad["database"]] = b"damaged download"
    assert not store.refresh()
    assert store.get().manifest["version"] == "one"
    assert json.loads((local / "published" / "manifest.json").read_text())["version"] == "one"
    assert not list((local / "published").glob(".download-*"))


@pytest.mark.parametrize("url", [
    "http://example.com/file", "https://user:secret@example.com/file", "https://localhost/file",
    "https://example.com:8080/file", "https://service.internal/file", "https://example.com/file#fragment",
])
def test_remote_url_rejects_unsafe_destinations(url):
    with pytest.raises(SnapshotError):
        snapshots._safe_url(url)


def test_remote_url_rejects_private_dns(monkeypatch):
    monkeypatch.setattr(snapshots.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(SnapshotError, match="non-public"):
        snapshots._safe_url("https://public-looking.example/file")
