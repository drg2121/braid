"""Reading and writing ``.jwlibrary`` backup archives.

A ``.jwlibrary`` file is a plain ZIP archive containing:

* ``userData.db``    -- the SQLite database with notes, highlights, tags,
                        bookmarks and playlists;
* ``manifest.json``  -- metadata describing the backup (schema version,
                        device name, timestamps and a hash);
* zero or more media blobs referenced by ``IndependentMedia.FilePath`` and
  ``PlaylistItem.ThumbnailFilePath``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

DB_NAME = "userData.db"
MANIFEST_NAME = "manifest.json"

#: Schema versions this tool has been validated against.
SUPPORTED_SCHEMA_VERSIONS = frozenset({14, 15, 16})


class ArchiveError(RuntimeError):
    """Raised when an archive is missing required members or is malformed."""


@dataclass
class Manifest:
    """The parsed contents of ``manifest.json``."""

    name: str
    creation_date: str
    version: int
    type: int
    schema_version: int
    database_name: str
    device_name: str
    last_modified_date: str
    hash: str
    extra: dict = field(default_factory=dict)
    backup_extra: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: dict) -> Manifest:
        try:
            backup = raw["userDataBackup"]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ArchiveError("manifest.json has no 'userDataBackup' section") from exc

        known_top = {"name", "creationDate", "version", "type", "userDataBackup"}
        known_backup = {
            "schemaVersion",
            "databaseName",
            "deviceName",
            "lastModifiedDate",
            "hash",
        }
        return cls(
            name=raw.get("name", ""),
            creation_date=raw.get("creationDate", ""),
            version=int(raw.get("version", 1)),
            type=int(raw.get("type", 0)),
            schema_version=int(backup["schemaVersion"]),
            database_name=backup.get("databaseName", DB_NAME),
            device_name=backup.get("deviceName", ""),
            last_modified_date=backup.get("lastModifiedDate", ""),
            hash=backup.get("hash", ""),
            extra={k: v for k, v in raw.items() if k not in known_top},
            backup_extra={k: v for k, v in backup.items() if k not in known_backup},
        )

    def to_dict(self) -> dict:
        backup = {
            "schemaVersion": self.schema_version,
            "databaseName": self.database_name,
            "deviceName": self.device_name,
            "lastModifiedDate": self.last_modified_date,
            "hash": self.hash,
        }
        backup.update(self.backup_extra)
        out = {
            "name": self.name,
            "creationDate": self.creation_date,
            "version": self.version,
            "type": self.type,
            "userDataBackup": backup,
        }
        out.update(self.extra)
        return out


class Backup:
    """An extracted ``.jwlibrary`` archive on a scratch directory.

    Use as a context manager; the scratch directory is removed on exit.
    """

    def __init__(self, path: Path, workdir: Path, manifest: Manifest) -> None:
        self.path = path
        self.workdir = workdir
        self.manifest = manifest
        self._own_workdir = False

    # -- construction ---------------------------------------------------

    @classmethod
    def open(cls, path: Path, workdir: Path | None = None) -> Backup:
        path = Path(path)
        if not zipfile.is_zipfile(path):
            raise ArchiveError(f"{path} is not a ZIP archive (expected .jwlibrary)")

        own = workdir is None
        target = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="braid-"))
        target.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(path) as zf:
            names = [m.filename for m in zf.infolist() if not m.is_dir()]

            # A backup exported by JW Library holds userData.db at the top.
            # A zipped copy of the app's own Userdata folder -- which is how a
            # Shortcut can fetch a library with no tapping -- nests it one level
            # down and may carry a stale manifest or none at all.
            db_member = next(
                (n for n in names if n == DB_NAME),
                next((n for n in names if PurePosixPath(n).name == DB_NAME), None),
            )
            if db_member is None:
                raise ArchiveError(f"{path} contains no {DB_NAME}")
            prefix = db_member[: -len(DB_NAME)]

            manifest_member = prefix + MANIFEST_NAME
            manifest = (
                Manifest.parse(json.loads(zf.read(manifest_member)))
                if manifest_member in names
                else None
            )

            for member in zf.infolist():
                if member.is_dir():
                    continue
                # Reject absolute paths and traversal before extracting.
                name = member.filename
                if name.startswith("/") or ".." in Path(name).parts:
                    raise ArchiveError(f"{path} contains an unsafe member path: {name}")
                zf.extract(member, target)

        # Flatten a nested folder so everything downstream sees a plain backup.
        if prefix:
            nested = target / prefix.rstrip("/")
            for entry in list(nested.iterdir()):
                # replace(), not rename(): on Windows rename() refuses when
                # something is already there, and a stale top-level file must
                # not stop a folder from being read.
                entry.replace(target / entry.name)
            nested.rmdir()

        db_path = target / DB_NAME
        _fold_in_write_ahead_log(db_path)

        if manifest is None:
            manifest = _manifest_for(db_path, path)
        manifest.database_name = DB_NAME

        backup = cls(path, target, manifest)
        backup._own_workdir = own
        return backup

    def __enter__(self) -> Backup:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._own_workdir and self.workdir.exists():
            shutil.rmtree(self.workdir, ignore_errors=True)

    # -- accessors ------------------------------------------------------

    @property
    def db_path(self) -> Path:
        return self.workdir / self.manifest.database_name

    def connect(self, readonly: bool = True) -> sqlite3.Connection:
        uri = f"file:{self.db_path}?mode={'ro' if readonly else 'rw'}"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def media_files(self) -> Iterator[Path]:
        """Every extracted member that is media, not database machinery.

        The sidecars have to be excluded by name rather than by what was
        extracted: the database header still says WAL, so merely opening it to
        read a row recreates ``-shm`` beside it, and anything left in this list
        gets written into the merged archive.
        """
        db = self.manifest.database_name
        skip = {db, MANIFEST_NAME, f"{db}-wal", f"{db}-shm", f"{db}-journal"}
        for entry in sorted(self.workdir.rglob("*")):
            name = entry.relative_to(self.workdir).as_posix()
            if entry.is_file() and name not in skip:
                yield entry

    def sort_key(self) -> str:
        """Timestamp used to order backups oldest-first when merging."""
        return self.manifest.last_modified_date or self.manifest.creation_date


def _fold_in_write_ahead_log(db_path: Path) -> None:
    """Checkpoint a ``-wal`` sitting beside the database, then remove it.

    JW Library runs in WAL mode, where the main file can be a near-empty shell
    while the log holds everything. SQLite folds the log in as soon as it opens
    the pair, so a checkpoint and a close is all it takes -- but it has to
    happen, or the library would look empty.
    """
    wal = db_path.with_name(db_path.name + "-wal")
    if not wal.is_file() or wal.stat().st_size == 0:
        for suffix in ("-wal", "-shm"):
            sidecar = db_path.with_name(db_path.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
        return

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()
    for suffix in ("-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()


def _manifest_for(db_path: Path, source: Path) -> Manifest:
    """Describe a library that arrived without a manifest of its own.

    Also the point at which a file that is not a JW Library database gets
    refused, with a sentence someone can act on rather than a SQLite error.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "LastModified" not in tables or "Location" not in tables:
            raise ArchiveError(
                f"{source.name} contains a database, but not a JW Library one "
                "-- it has none of the tables a personal study library has"
            )

        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if not schema_version and "grdb_migrations" in tables:
            rows = [r[0] for r in conn.execute("SELECT identifier FROM grdb_migrations")]
            numbers = [int(r[1:]) for r in rows if r[1:].isdigit()]
            schema_version = max(numbers) if numbers else 0
        row = conn.execute("SELECT LastModified FROM LastModified").fetchone()
        last_modified = row[0] if row else ""
    except sqlite3.DatabaseError as exc:
        raise ArchiveError(
            f"{source.name} does not hold a readable database: {exc}"
        ) from exc
    finally:
        conn.close()

    return Manifest(
        name=source.name,
        creation_date=_iso_local(),
        version=1,
        type=0,
        schema_version=schema_version,
        database_name=DB_NAME,
        device_name=source.stem,
        last_modified_date=last_modified,
        hash="",
    )


def db_last_modified(db_path: Path) -> str:
    """Read the single ``LastModified`` row from a userData database."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT LastModified FROM LastModified").fetchone()
    finally:
        conn.close()
    return row[0] if row else ""


def jw_hex(digest: bytes) -> str:
    """Format a digest the way JW Library does.

    The app renders each byte with a ``%x``-style format instead of ``%02x``,
    so bytes below 0x10 lose their leading zero and the string is usually
    shorter than the 64 characters a SHA-256 hex digest would normally have.
    ``IndependentMedia.Hash`` uses this encoding; matching it byte for byte is
    what lets us recognise the same media file across devices.
    """
    return "".join(format(b, "x") for b in digest)


def media_hash(path: Path) -> str:
    """The ``IndependentMedia.Hash`` value for a file on disk."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return jw_hex(digest.digest())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_path(path: Path) -> Path:
    """A path that does not exist yet, by appending ``-2``, ``-3`` and so on.

    Merged output is named after the current minute, so two merges in quick
    succession -- or a merge into a folder that already holds an earlier
    result -- would otherwise overwrite a file that may itself be an input.
    """
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for n in range(2, 1000):
        candidate = path.with_name(f"{stem}-{n}{suffix}")
        if not candidate.exists():
            return candidate
    raise ArchiveError(f"could not find a free name next to {path}")


def _iso_local() -> str:
    """Timestamp in the format JW Library writes, e.g. ``2026-08-29T19:26:05+0300``."""
    return datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def write_backup(
    out_path: Path,
    db_path: Path,
    media: dict[str, Path],
    manifest: Manifest,
    *,
    hash_mode: str = "sha256",
) -> Path:
    """Write a ``.jwlibrary`` archive.

    ``media`` maps the archive member name to a file on disk. ``hash_mode``
    selects what goes into ``manifest.userDataBackup.hash``:

    ``sha256``  SHA-256 of the written database in JW Library's own ``jw_hex``
                encoding. The value JW Library itself stores here is not a hash
                of the exported file, so it cannot be reproduced exactly; every
                known third-party tool regenerates it and restores still work.
    ``keep``    reuse the hash carried by ``manifest``;
    ``empty``   write an empty string.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    manifest.name = out_path.name
    manifest.creation_date = _iso_local()
    manifest.last_modified_date = manifest.last_modified_date or manifest.creation_date

    if hash_mode == "sha256":
        manifest.hash = media_hash(db_path)
    elif hash_mode == "empty":
        manifest.hash = ""
    elif hash_mode != "keep":
        raise ValueError(f"unknown hash_mode: {hash_mode!r}")

    tmp = out_path.with_suffix(out_path.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest.to_dict(), ensure_ascii=False))
        zf.write(db_path, manifest.database_name)
        for member, source in sorted(media.items()):
            zf.write(source, member)
    tmp.replace(out_path)
    return out_path


__all__ = [
    "ArchiveError",
    "Backup",
    "Manifest",
    "DB_NAME",
    "MANIFEST_NAME",
    "SUPPORTED_SCHEMA_VERSIONS",
    "db_last_modified",
    "jw_hex",
    "media_hash",
    "sha256_file",
    "unique_path",
    "write_backup",
]
