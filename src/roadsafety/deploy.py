"""Versioned GitHub publications and recoverable hosted pipeline state.

Serving releases are immutable once published. Operational archives are separate
prereleases, so a failed ingestion can save its evidence without replacing the
last successful public database. Credentials are read only from the environment.
"""
from __future__ import annotations

import hashlib
import gzip
import json
import os
import re
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse
from uuid import uuid4

import httpx

from .snapshots import validate_manifest, verify_database


STATE_TAG = "operations-state"
STATE_DIRECTORIES = ("landing", "raw", "runs", "quarantine", "incidents", "reports", "investigations")
STATE_FILES = ("warehouse.duckdb", "source_verification.json", "transformations.sql", "published/manifest.json", "evidence-index.json")
MAX_ASSET_BYTES = 1_900_000_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class GitHub:
    def __init__(self, repository: str | None, token: str | None, client: httpx.Client | None):
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise ValueError("Set GITHUB_REPOSITORY to owner/repository")
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.client = client or httpx.Client(timeout=120, follow_redirects=True)
        self.owned_client = client is None
        self.base = f"https://api.github.com/repos/{self.repository}"

    def close(self) -> None:
        if self.owned_client:
            self.client.close()

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if method != "GET" and not self.token:
            raise ValueError("GITHUB_TOKEN is required for publication")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        headers.update(kwargs.pop("headers", {}))
        url = path if path.startswith("https://") else self.base + path
        response = self.client.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def release(self, tag: str) -> dict | None:
        try:
            return self.request("GET", "/releases/tags/" + quote(tag, safe="")).json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    def assets(self, release: dict) -> list[dict]:
        assets = []
        page = 1
        while True:
            batch = self.request("GET", f"/releases/{release['id']}/assets", params={"per_page": 100, "page": page}).json()
            assets.extend(batch)
            if len(batch) < 100:
                return assets
            page += 1

    def upload(self, release: dict, path: Path, content_type: str = "application/octet-stream") -> dict:
        size = path.stat().st_size
        if size > MAX_ASSET_BYTES:
            raise ValueError("Asset exceeds the course publication size limit")
        upload_url = release["upload_url"].split("{", 1)[0]
        if urlparse(upload_url).hostname != "uploads.github.com":
            raise ValueError("Unexpected GitHub upload destination")
        with path.open("rb") as stream:
            return self.request("POST", upload_url, params={"name": path.name},
                                content=stream, headers={"Content-Type": content_type,
                                                         "Content-Length": str(size)}).json()

    def download(self, asset: dict, destination: Path) -> None:
        # The asset API returns a redirect when octet-stream is requested. httpx
        # strips Authorization on cross-origin redirects to storage hosts.
        url = asset["url"]
        if not url.startswith(self.base + "/releases/assets/"):
            raise ValueError("Unexpected GitHub asset destination")
        headers = {"Accept": "application/octet-stream", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        total = 0
        with self.client.stream("GET", url, headers=headers, follow_redirects=True) as response:
            response.raise_for_status()
            with destination.open("wb") as stream:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_ASSET_BYTES:
                        raise ValueError("Downloaded state exceeds the course size limit")
                    stream.write(chunk)
        expected = asset.get("digest", "")
        if expected.startswith("sha256:") and _sha256(destination) != expected.split(":", 1)[1]:
            raise ValueError("GitHub asset checksum mismatch")


def publish(data_dir: Path, *, repository: str | None = None, token: str | None = None,
            client: httpx.Client | None = None) -> dict:
    """Publish a serving release and retain evidence if deployment itself fails."""
    try:
        return _publish(Path(data_dir), repository=repository, token=token, client=client)
    except Exception as exc:
        now = datetime.now(timezone.utc)
        run_id = "publish-" + now.strftime("%Y%m%dT%H%M%S%fZ")
        run = {"run_id": run_id, "status": "failed", "started_at": now.isoformat(),
               "finished_at": now.isoformat(), "source_mode": "live",
               "error": {"stage": "publication", "type": type(exc).__name__,
                         "message": "Publication did not complete; inspect the workflow diagnostics. The previous release is retained."}}
        path = Path(data_dir) / "runs" / (run_id + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(run, indent=2) + "\n")
        raise


def _publish(data_dir: Path, *, repository: str | None = None, token: str | None = None,
             client: httpx.Client | None = None) -> dict:
    """Publish a verified live serving snapshot; the manifest is uploaded last."""
    directory = Path(data_dir) / "published"
    manifest_path = directory / "manifest.json"
    manifest = validate_manifest(json.loads(manifest_path.read_text()))
    version = str(manifest["version"])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", version):
        raise ValueError("Invalid publication version")
    filename = manifest["database"]
    if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".duckdb"):
        raise ValueError("Manifest database must be a DuckDB basename")
    database = directory / filename
    if database.is_symlink() or database.resolve().parent != directory.resolve():
        raise ValueError("Database must be inside the publication directory")
    if manifest.get("schema_version") != 1 or manifest.get("source_mode") != "live":
        raise ValueError("Only schema-v1 live publications can be released")
    if _sha256(database) != manifest["sha256"]:
        raise ValueError("Publication database checksum mismatch")
    verify_database(database, manifest)
    github = GitHub(repository, token, client)
    try:
        tag = "data-" + version
        remote_manifest = dict(manifest, database_url=(
            f"https://github.com/{github.repository}/releases/download/{quote(tag, safe='')}/{quote(filename, safe='')}"
        ))
        release = github.release(tag)
        if release and not release.get("draft"):
            assets = github.assets(release)
            names = {asset["name"] for asset in assets}
            if filename not in names or "manifest.json" not in names:
                raise ValueError("Existing immutable release is incomplete")
            with tempfile.TemporaryDirectory() as temporary:
                downloaded_manifest = Path(temporary) / "manifest.json"
                github.download(next(a for a in assets if a["name"] == "manifest.json"), downloaded_manifest)
                if json.loads(downloaded_manifest.read_text()) != remote_manifest:
                    raise ValueError("Version already exists with a different manifest")
            # Do not promote an old rerun over a newer successful release.
            return {"status": "already_published", "tag": tag, "url": release["html_url"]}
        if release is None:
            release = github.request("POST", "/releases", json={
                "tag_name": tag, "name": f"Road safety data {version}",
                "draft": True, "prerelease": False, "make_latest": "false",
                "target_commitish": os.environ.get("GITHUB_SHA", "main"),
                "body": "Validated serving snapshot. See manifest.json for source, window, quality, and checksum.",
            }).json()
        # A previous interrupted draft is safe to retry; published releases are
        # never overwritten. The prior public latest release remains untouched.
        for asset in github.assets(release):
            if asset["name"] in {filename, "manifest.json"}:
                github.request("DELETE", f"/releases/assets/{asset['id']}")
        github.upload(release, database)
        with tempfile.TemporaryDirectory() as temporary:
            exported_manifest = Path(temporary) / "manifest.json"
            exported_manifest.write_text(json.dumps(remote_manifest, indent=2) + "\n")
            github.upload(release, exported_manifest, "application/json")
        published = github.request("PATCH", f"/releases/{release['id']}", json={
            "draft": False, "make_latest": "true",
        }).json()
        return {"status": "published", "tag": tag, "url": published["html_url"]}
    finally:
        github.close()


def _state_paths(data_dir: Path) -> list[Path]:
    paths = [data_dir / name for name in STATE_FILES if (data_dir / name).exists()]
    for name in STATE_DIRECTORIES:
        root = data_dir / name
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(path for path in paths if not path.name.endswith((".tmp", ".wal", ".lock")))


def _batch_files(data_dir: Path, batch: Path) -> list[Path]:
    files = []
    for path in sorted(batch.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(data_dir.resolve()):
            raise ValueError("Raw evidence cannot contain symlinks")
        if path.is_file():
            files.append(path)
    return files


def _batch_time(batch: Path) -> float:
    for name in ("manifest.json", "provenance.json"):
        try:
            value = json.loads((batch / name).read_text())
            stamp = value.get("acquired_at") or value.get("generated_at")
            if stamp:
                return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return max((path.stat().st_mtime for path in batch.rglob("*") if path.is_file()), default=batch.stat().st_mtime)


def _archive_older_evidence(data_dir: Path, github: GitHub, keep_batches: int) -> set[Path]:
    """Archive old batches before excluding them from the recovery bundle.

    The files remain locally untouched. Each content-addressed prerelease has one
    immutable asset, avoiding the per-release asset limit as history grows.
    """
    index_path = data_dir / "evidence-index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
        if index.get("schema_version") != 1 or not isinstance(index.get("archives"), list):
            raise ValueError("Unsupported raw-evidence index")
    else:
        index = {"schema_version": 1, "archives": []}
    omitted = set()
    for relative in ("raw", "landing/live"):
        root = data_dir / relative
        if not root.exists():
            continue
        if root.is_symlink():
            raise ValueError("Raw evidence cannot contain symlinks")
        batches = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: (_batch_time(path), path.name), reverse=True)
        for batch in batches[keep_batches:]:
            files = _batch_files(data_dir, batch)
            if not files:
                continue
            relative_batch = batch.relative_to(data_dir).as_posix()
            file_checksums = [(path.relative_to(batch).as_posix(), _sha256(path)) for path in files]
            tree_digest = hashlib.sha256(json.dumps(file_checksums, separators=(",", ":")).encode()).hexdigest()
            previous = next((entry for entry in index["archives"]
                             if entry.get("batch") == relative_batch and entry.get("tree_sha256") == tree_digest
                             and entry.get("upload_confirmed") is True), None)
            if previous is not None:
                omitted.add(batch)
                continue
            with tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "evidence.tar.gz"
                # Normalize archive metadata so the same exact bytes produce the
                # same asset hash after restore or a retried hosted operation.
                with archive.open("wb") as output, gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w", dereference=True) as tar:
                        for path in files:
                            info = tar.gettarinfo(str(path), arcname=path.relative_to(data_dir).as_posix())
                            info.uid = info.gid = 0
                            info.uname = info.gname = ""
                            info.mtime = 0
                            info.mode = 0o644
                            with path.open("rb") as content:
                                tar.addfile(info, content)
                digest = _sha256(archive)
                filename = f"evidence-{digest}.tar.gz"
                named_archive = archive.with_name(filename)
                archive.rename(named_archive)
                tag = "evidence-" + digest
                release = github.release(tag)
                if release is None:
                    release = github.request("POST", "/releases", json={
                        "tag_name": tag, "name": f"Raw evidence {relative_batch}",
                        "draft": False, "prerelease": True, "make_latest": "false",
                        "body": f"Immutable original evidence for {relative_batch}. SHA-256: {digest}",
                    }).json()
                existing = next((asset for asset in github.assets(release) if asset["name"] == filename), None)
                if existing is not None:
                    if existing.get("state") != "uploaded":
                        raise ValueError("Existing raw evidence upload is incomplete")
                    downloaded = Path(temporary) / "verified.tar.gz"
                    github.download(existing, downloaded)
                    if _sha256(downloaded) != digest:
                        raise ValueError("Existing immutable raw evidence checksum mismatch")
                    uploaded = existing
                else:
                    uploaded = github.upload(release, named_archive, "application/gzip")
                    if uploaded.get("state") != "uploaded":
                        raise ValueError("Raw evidence upload was not confirmed")
                    server_digest = uploaded.get("digest", "")
                    if server_digest and server_digest != "sha256:" + digest:
                        raise ValueError("Uploaded raw evidence checksum mismatch")
                    if not server_digest:
                        downloaded = Path(temporary) / "verified.tar.gz"
                        github.download(uploaded, downloaded)
                        if _sha256(downloaded) != digest:
                            raise ValueError("Uploaded raw evidence did not round-trip")
                index["archives"].append({
                    "batch": relative_batch, "tree_sha256": tree_digest, "sha256": digest,
                    "release_tag": tag, "asset_id": uploaded["id"],
                    "asset_url": uploaded["url"],
                    "download_url": f"https://github.com/{github.repository}/releases/download/{tag}/{filename}",
                    "file_count": len(files), "expanded_bytes": sum(path.stat().st_size for path in files),
                    "upload_confirmed": True, "archived_at": datetime.now(timezone.utc).isoformat(),
                })
                data_dir.mkdir(parents=True, exist_ok=True)
                temporary_index = index_path.with_suffix(".json.tmp")
                temporary_index.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
                temporary_index.replace(index_path)
                omitted.add(batch)
    return omitted


def persist_operations(data_dir: Path, *, repository: str | None = None, token: str | None = None,
                       client: httpx.Client | None = None, keep_archives: int = 7,
                       keep_raw_batches: int = 2) -> dict:
    """Save complete operational state, including failed runs and budget ledger.

    New archives are uploaded before older ones are pruned. At least two complete
    archives are retained. Serving releases and their latest pointer are untouched.
    """
    if keep_archives < 2:
        raise ValueError("Retain at least two operational state archives")
    if keep_raw_batches < 1:
        raise ValueError("Retain at least one recent batch per raw source locally")
    data_dir = Path(data_dir)
    github = GitHub(repository, token, client)
    try:
        omitted_batches = _archive_older_evidence(data_dir, github, keep_raw_batches)
        release = github.release(STATE_TAG)
        if release is None:
            release = github.request("POST", "/releases", json={
                "tag_name": STATE_TAG, "name": "Operational state and evidence",
                "draft": False, "prerelease": True, "make_latest": "false",
                "body": "Versioned recovery archives, including failed runs. This is not a serving publication.",
            }).json()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        name = f"state-{timestamp}-{uuid4().hex[:8]}.tar.gz"
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / name
            with tarfile.open(archive, "w:gz", dereference=True) as tar:
                for path in _state_paths(data_dir):
                    if any(path.is_relative_to(batch) for batch in omitted_batches):
                        continue
                    if path.is_symlink() or not path.resolve().is_relative_to(data_dir.resolve()):
                        raise ValueError("Operational state cannot contain symlinks")
                    tar.add(path, arcname=path.relative_to(data_dir).as_posix(), recursive=False)
            uploaded = github.upload(release, archive, "application/gzip")
            if uploaded.get("state") != "uploaded":
                raise ValueError("State upload was not confirmed")
        archives = sorted((a for a in github.assets(release) if re.fullmatch(r"state-[\w-]+\.tar\.gz", a["name"])),
                          key=lambda a: a["name"], reverse=True)
        for old in archives[keep_archives:]:
            github.request("DELETE", f"/releases/assets/{old['id']}")
        return {"status": "saved", "asset": name, "release": STATE_TAG,
                "archived_evidence_batches": len(omitted_batches), "recent_batches_per_source": keep_raw_batches}
    finally:
        github.close()


def restore_state(data_dir: Path, *, repository: str | None = None, token: str | None = None,
                  client: httpx.Client | None = None) -> bool:
    """Restore the newest complete archive into an empty managed state directory."""
    data_dir = Path(data_dir)
    if _state_paths(data_dir):
        raise ValueError("Restore requires an empty managed state directory; existing local work is preserved")
    github = GitHub(repository, token, client)
    try:
        release = github.release(STATE_TAG)
        if release is None:
            return False
        archives = sorted((a for a in github.assets(release)
                           if re.fullmatch(r"state-[\w-]+\.tar\.gz", a["name"]) and a.get("state") == "uploaded"),
                          key=lambda a: a["name"], reverse=True)
        if not archives:
            return False
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "state.tar.gz"
            github.download(archives[0], archive)
            extracted = Path(temporary) / "state"
            extracted.mkdir()
            total = 0
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar.getmembers():
                    name = PurePosixPath(member.name)
                    if name.is_absolute() or ".." in name.parts or not member.isfile():
                        raise ValueError("Unsafe operational archive member")
                    if name.as_posix() not in STATE_FILES and not (
                        len(name.parts) > 1 and name.parts[0] in STATE_DIRECTORIES
                    ):
                        raise ValueError("Unexpected operational archive path")
                    total += member.size
                    if total > MAX_ASSET_BYTES:
                        raise ValueError("Expanded state exceeds course size limit")
                    destination = extracted.joinpath(*name.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source = tar.extractfile(member)
                    if source is None:
                        raise ValueError("Missing archive file body")
                    with source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)
            data_dir.mkdir(parents=True, exist_ok=True)
            for path in extracted.iterdir():
                target = data_dir / path.name
                if target.exists():
                    raise ValueError("Restore would replace an existing local path")
                shutil.move(str(path), target)
        return True
    finally:
        github.close()
