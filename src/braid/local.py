"""Read and write the JW Library installed on this computer.

On a desktop the library is not a file you export -- it is a live SQLite
database inside the app's own folder. Reaching it directly removes the two
manual steps on this machine: no Create Backup, no Restore Backup. Phones and
tablets still need those taps, because their storage is not reachable from
here.

Everything in this module treats that database as precious:

* reads take a consistent snapshot with ``VACUUM INTO``, which is safe even
  while JW Library is running;
* writes refuse to run at all while JW Library is open, and always copy the
  existing database aside first.
"""

from __future__ import annotations

import glob
import os
import platform
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .archive import Backup, Manifest, write_backup

DB_NAME = "userData.db"
#: SQLite writes these alongside the database in WAL mode. On this platform the
#: main file can be almost empty while the -wal holds nearly everything, so all
#: three must be handled together.
SIDECARS = ("-wal", "-shm")

#: Where a copy of the live database is put before anything is written to it.
SAFETY_DIRNAME = "braid-safety-copies"


class LocalLibraryError(RuntimeError):
    """Raised when the local library cannot be read or written safely."""


def _schema_version(conn: sqlite3.Connection) -> int:
    """The database's schema version.

    JW Library stores it in ``PRAGMA user_version``, but a database restored
    from a backup can carry a zero there while its migration ledger is
    correct, so fall back to the highest ``vN`` migration that has been run.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version:
        return int(version)
    try:
        rows = [r[0] for r in conn.execute("SELECT identifier FROM grdb_migrations")]
    except sqlite3.OperationalError:
        return 0
    numbers = [
        int(identifier[1:])
        for identifier in rows
        if identifier.startswith("v") and identifier[1:].isdigit()
    ]
    return max(numbers) if numbers else 0


@dataclass
class LocalLibrary:
    """A JW Library installation's data folder on this computer."""

    path: Path

    @property
    def db_path(self) -> Path:
        return self.path / DB_NAME

    def exists(self) -> bool:
        return self.db_path.is_file()

    def schema_version(self) -> int:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            return _schema_version(conn)
        finally:
            conn.close()

    def counts(self) -> dict[str, int]:
        from .merge import COUNTED_TABLES

        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            out = {}
            for table in COUNTED_TABLES:
                try:
                    out[table] = conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                except sqlite3.OperationalError:
                    continue
            return out
        finally:
            conn.close()

    def media_files(self) -> dict[str, Path]:
        """Archive member name -> file on disk, for everything the DB references."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            wanted = {r[0] for r in conn.execute("SELECT FilePath FROM IndependentMedia")}
            wanted |= {
                r[0]
                for r in conn.execute(
                    "SELECT ThumbnailFilePath FROM PlaylistItem"
                    " WHERE ThumbnailFilePath IS NOT NULL"
                )
            }
        finally:
            conn.close()

        out: dict[str, Path] = {}
        for name in sorted(wanted):
            candidate = self.path / name
            if candidate.is_file():
                out[name] = candidate
        return out

    # -- reading --------------------------------------------------------

    def export(self, out_path: Path, device_name: str | None = None) -> Path:
        """Write the live library out as a ``.jwlibrary`` archive.

        ``VACUUM INTO`` produces a consistent snapshot that already folds in
        the write-ahead log, so this is safe to run while JW Library is open.
        """
        if not self.exists():
            raise LocalLibraryError(f"no {DB_NAME} in {self.path}")

        with tempfile.TemporaryDirectory(prefix="braid-export-") as tmp:
            snapshot = Path(tmp) / DB_NAME
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            try:
                conn.execute("VACUUM INTO ?", (str(snapshot),))
            finally:
                conn.close()

            last_modified = ""
            check = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
            try:
                row = check.execute("SELECT LastModified FROM LastModified").fetchone()
                last_modified = row[0] if row else ""
                schema_version = _schema_version(check)
            finally:
                check.close()

            manifest = Manifest(
                name=Path(out_path).name,
                creation_date="",
                version=1,
                type=0,
                schema_version=schema_version,
                database_name=DB_NAME,
                device_name=device_name or default_device_name(),
                last_modified_date=last_modified,
                hash="",
            )
            return write_backup(out_path, snapshot, self.media_files(), manifest)

    # -- writing --------------------------------------------------------

    def is_running(self) -> bool:
        return jw_library_is_running()

    def safety_copy(self, into: Path | None = None) -> Path:
        """Copy the current database (and its WAL sidecars) somewhere safe."""
        into = Path(into) if into else Path.home() / SAFETY_DIRNAME
        into.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        target = into / f"userData-before-{stamp}"
        target.mkdir()
        for suffix in ("",) + SIDECARS:
            source = self.db_path.with_name(DB_NAME + suffix)
            if source.is_file():
                shutil.copy2(source, target / source.name)
        return target

    def install(self, backup_path: Path, *, safety_dir: Path | None = None) -> dict:
        """Replace the live library with the contents of a ``.jwlibrary``.

        Refuses while JW Library is running, because writing under a live
        connection in WAL mode can leave the database inconsistent.
        """
        if not self.exists():
            raise LocalLibraryError(f"no {DB_NAME} in {self.path}")
        if self.is_running():
            raise LocalLibraryError(
                "JW Library is running. Quit it completely, then run this again "
                "-- writing to its database while it is open risks corrupting it."
            )

        before = self.counts()
        saved = self.safety_copy(safety_dir)

        with Backup.open(Path(backup_path)) as backup:
            # Flatten the incoming database so no stale WAL is left behind.
            with tempfile.TemporaryDirectory(prefix="braid-install-") as tmp:
                staged = Path(tmp) / DB_NAME
                conn = sqlite3.connect(f"file:{backup.db_path}?mode=ro", uri=True)
                try:
                    conn.execute("VACUUM INTO ?", (str(staged),))
                finally:
                    conn.close()

                # Drop the live WAL first; a leftover -wal would be replayed
                # over the database we are about to put in place.
                for suffix in SIDECARS:
                    sidecar = self.db_path.with_name(DB_NAME + suffix)
                    if sidecar.exists():
                        sidecar.unlink()

                shutil.copy2(staged, self.db_path)

                copied = 0
                for entry in backup.media_files():
                    name = entry.relative_to(backup.workdir).as_posix()
                    target = self.path / name
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(entry, target)
                        copied += 1

        after = self.counts()
        return {
            "safetyCopy": str(saved),
            "mediaCopied": copied,
            "before": before,
            "after": after,
        }


# -- discovery -------------------------------------------------------------


def _macos_candidates() -> list[Path]:
    home = Path.home()
    patterns = [
        # "Designed for iPad" builds get a UUID-named container.
        str(home / "Library/Containers/*/Data/Documents/Userdata"),
        str(home / "Library/Containers/org.jw.jwlibrary/Data/Documents/Userdata"),
        str(home / "Library/Application Support/JW Library"),
    ]
    return [Path(p) for pattern in patterns for p in glob.glob(pattern)]


def _windows_candidates() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    patterns = [
        str(Path(local) / "Packages" / "*JWLibrary*" / "LocalState" / "Userdata"),
        str(Path(local) / "Packages" / "*jw.org*" / "LocalState" / "Userdata"),
        str(Path(local) / "JW Library" / "Userdata"),
    ]
    return [Path(p) for pattern in patterns for p in glob.glob(pattern)]


def find_libraries() -> list[LocalLibrary]:
    """Every JW Library data folder this computer appears to have."""
    system = platform.system()
    if system == "Darwin":
        candidates = _macos_candidates()
    elif system == "Windows":
        candidates = _windows_candidates()
    else:
        candidates = []

    found: list[LocalLibrary] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        library = LocalLibrary(resolved)
        if library.exists():
            seen.add(resolved)
            found.append(library)
    return found


def find_library() -> LocalLibrary:
    """The single local library, or an error explaining what to do instead."""
    found = find_libraries()
    if not found:
        raise LocalLibraryError(
            "no JW Library installation found on this computer. Only the "
            "macOS and Windows apps keep a library here; phones and tablets "
            "have to export a backup into the shared folder by hand."
        )
    if len(found) > 1:
        listed = "\n  ".join(str(library.path) for library in found)
        raise LocalLibraryError(
            f"found more than one JW Library data folder:\n  {listed}\n"
            "Pass the one you want with --library."
        )
    return found[0]


def jw_library_is_running() -> bool:
    """Whether a JW Library process is currently open."""
    if platform.system() == "Windows":
        try:
            out = subprocess.run(
                ["tasklist"], capture_output=True, text=True, timeout=15
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return "jwlibrary" in out.lower()

    try:
        out = subprocess.run(
            ["ps", "-Ao", "comm="], capture_output=True, text=True, timeout=15
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    lowered = out.lower()
    return "jwlibrary" in lowered or "jw library" in lowered


def default_device_name() -> str:
    return platform.node().split(".")[0] or "this computer"


__all__ = [
    "DB_NAME",
    "SAFETY_DIRNAME",
    "LocalLibrary",
    "LocalLibraryError",
    "default_device_name",
    "find_libraries",
    "find_library",
    "jw_library_is_running",
]
