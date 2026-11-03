"""Validate immutable serving databases and switch only to complete snapshots."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import tempfile
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import duckdb

MAX_MANIFEST_BYTES = 64 * 1024
MAX_DATABASE_BYTES = 256 * 1024 * 1024
TABLE_COLUMNS = {
    "gold_daily": {
        "crash_date": "DATE", "borough": "VARCHAR", "collisions": "BIGINT",
        "injured": "BIGINT", "killed": "BIGINT", "missing_location": "BIGINT",
    },
    "gold_vehicles": {
        "crash_date": "DATE", "borough": "VARCHAR", "vehicle_type": "VARCHAR",
        "involved_vehicles": "BIGINT",
    },
}


class SnapshotError(ValueError):
    """An untrusted or incomplete publication cannot become the serving version."""


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise SnapshotError("generated_at must be a timezone-aware UTC timestamp")
    return parsed


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SnapshotError("manifest must be an object")
    required = {
        "version", "database", "sha256", "schema_version", "generated_at",
        "source_mode", "window_start", "window_end", "source_max_crash_date", "quality",
    }
    if required - value.keys():
        raise SnapshotError("manifest is missing required fields")
    if not isinstance(value["version"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value["version"]):
        raise SnapshotError("invalid snapshot version")
    name = value["database"]
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.duckdb", name):
        raise SnapshotError("database must be a plain .duckdb filename")
    if not isinstance(value["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
        raise SnapshotError("invalid SHA-256 checksum")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise SnapshotError("unsupported serving schema version")
    if value["source_mode"] not in {"live", "fixture"} or not isinstance(value["quality"], dict):
        raise SnapshotError("invalid source mode or quality metadata")
    try:
        parse_timestamp(value["generated_at"])
        for field in ("window_start", "window_end", "source_max_crash_date"):
            if value[field] is not None and (not isinstance(value[field], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[field])):
                raise SnapshotError(f"{field} must use YYYY-MM-DD")
        start, end = date.fromisoformat(value["window_start"]), date.fromisoformat(value["window_end"])
        if start > end:
            raise SnapshotError("snapshot window is reversed")
        if value["source_max_crash_date"] is not None:
            date.fromisoformat(value["source_max_crash_date"])
    except (TypeError, AttributeError, ValueError) as exc:
        raise SnapshotError(f"invalid manifest date: {exc}") from exc
    return dict(value)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_database(path: Path, manifest: dict[str, Any]) -> None:
    if not path.is_file() or path.stat().st_size > MAX_DATABASE_BYTES:
        raise SnapshotError("database is missing or exceeds the serving size limit")
    if checksum(path) != manifest["sha256"]:
        raise SnapshotError("database checksum does not match manifest")
    try:
        with duckdb.connect(str(path), read_only=True, config={"enable_external_access": False}) as connection:
            for table, expected in TABLE_COLUMNS.items():
                relation = connection.execute(
                    "SELECT table_type FROM information_schema.tables WHERE table_schema = 'main' AND table_name = ?", [table]
                ).fetchone()
                if relation != ("BASE TABLE",):
                    raise SnapshotError(f"{table} must be a stored table")
                actual = {row[1]: row[2] for row in connection.execute(f"PRAGMA table_info('{table}')").fetchall()}
                if any(actual.get(name) != kind for name, kind in expected.items()):
                    raise SnapshotError(f"invalid serving schema for {table}")
    except duckdb.Error as exc:
        raise SnapshotError("database is not a valid serving snapshot") from exc


def _safe_url(url: str) -> str:
    if not isinstance(url, str):
        raise SnapshotError("snapshot URL must be a string")
    parsed = urlsplit(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment:
        raise SnapshotError("snapshot URLs must be public HTTPS URLs without credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SnapshotError("invalid URL port") from exc
    if port not in (None, 443) or "." not in host or host.endswith((".localhost", ".local", ".internal")):
        raise SnapshotError("snapshot URL is not a public HTTPS destination")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise SnapshotError("snapshot URL resolves to a non-public destination")
    except socket.gaierror as exc:
        raise SnapshotError("snapshot hostname could not be resolved") from exc
    return url


class _PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, _safe_url(newurl))


def _open_url(url: str):
    # Retain the environment's proxy and TLS trust settings. Redirects are checked too.
    request = Request(_safe_url(url), headers={"User-Agent": "roadsafety-course/1", "Accept": "application/json, application/octet-stream"})
    return build_opener(_PublicRedirects()).open(request, timeout=30)


@dataclass(frozen=True)
class Snapshot:
    manifest: dict[str, Any]
    database: Path


class SnapshotStore:
    """One immutable database per version, with a validated previous-manifest fallback."""

    def __init__(self, data_dir: Path, manifest_url: str | None = None):
        self.data_dir = Path(data_dir)
        self.published = self.data_dir / "published"
        self.manifest_url = manifest_url
        self._current: Snapshot | None = None
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self.last_error: str | None = None
        self.last_checked_at: str | None = None

    def get(self) -> Snapshot | None:
        with self._lock:
            return self._current

    def _database_path(self, manifest: dict[str, Any]) -> Path:
        path = self.published / manifest["database"]
        if path.is_symlink() or path.resolve().parent != self.published.resolve():
            raise SnapshotError("database path escapes the publication directory")
        return path

    def _read_manifest(self, path: Path) -> dict[str, Any]:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise SnapshotError("manifest is too large")
        return validate_manifest(json.loads(path.read_text()))

    def _load(self, path: Path) -> Snapshot:
        manifest = self._read_manifest(path)
        database = self._database_path(manifest)
        verify_database(database, manifest)
        return Snapshot(manifest, database)

    def _write_manifest(self, name: str, manifest: dict[str, Any]) -> None:
        self.published.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".manifest-", suffix=".json", dir=self.published)
        try:
            with os.fdopen(fd, "w") as target:
                json.dump(manifest, target, sort_keys=True)
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.published / name)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _accept(self, snapshot: Snapshot) -> None:
        with self._lock:
            if self._current and self._current.manifest["version"] == snapshot.manifest["version"]:
                if self._current.manifest != snapshot.manifest:
                    raise SnapshotError("an existing snapshot version cannot be changed")
            self._write_manifest(".last-good-manifest.json", snapshot.manifest)
            self._current = snapshot

    def _remote(self) -> Snapshot:
        with _open_url(self.manifest_url) as response:
            body = response.read(MAX_MANIFEST_BYTES + 1)
        if len(body) > MAX_MANIFEST_BYTES:
            raise SnapshotError("remote manifest is too large")
        manifest = validate_manifest(json.loads(body))
        destination = self._database_path(manifest)
        if destination.exists():
            verify_database(destination, manifest)
        else:
            self.published.mkdir(parents=True, exist_ok=True)
            database_url = manifest.get("database_url") or urljoin(self.manifest_url, manifest["database"])
            fd, temporary = tempfile.mkstemp(prefix=".download-", suffix=".duckdb", dir=self.published)
            try:
                total = 0
                with os.fdopen(fd, "wb") as target, _open_url(database_url) as response:
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_DATABASE_BYTES:
                            raise SnapshotError("remote database exceeds the serving size limit")
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                verify_database(Path(temporary), manifest)
                os.replace(temporary, destination)
            finally:
                Path(temporary).unlink(missing_ok=True)
        snapshot = Snapshot(manifest, destination)
        if self._current and self._current.manifest["version"] == manifest["version"] and self._current.manifest != manifest:
            raise SnapshotError("an existing snapshot version cannot be changed")
        self._write_manifest("manifest.json", manifest)
        return snapshot

    def refresh(self) -> bool:
        """Try publication updates; preserve the validated snapshot on any failure."""
        with self._refresh_lock:
            self.last_checked_at = datetime.now(timezone.utc).isoformat()
            try:
                if self._current is None:
                    try:
                        self._accept(self._load(self.published / "manifest.json"))
                    except (OSError, ValueError, duckdb.Error):
                        fallback = self.published / ".last-good-manifest.json"
                        if fallback.exists():
                            self._accept(self._load(fallback))
                snapshot = self._remote() if self.manifest_url else self._load(self.published / "manifest.json")
                self._accept(snapshot)
                self.last_error = None
                return True
            except (OSError, ValueError, duckdb.Error) as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                return False
