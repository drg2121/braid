from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from braid.archive import (
    ArchiveError,
    Backup,
    Manifest,
    jw_hex,
    media_hash,
    write_backup,
)


def test_jw_hex_drops_the_leading_zero_of_each_byte():
    # This is how JW Library itself formats IndependentMedia.Hash.
    assert jw_hex(bytes([0xA8, 0x09, 0x0D, 0x08, 0x02])) == "a89d82"
    assert jw_hex(bytes([0xFF, 0x00, 0x10])) == "ff010"


def test_media_hash_matches_jw_hex_of_sha256(tmp_path: Path):
    payload = b"some audio bytes"
    blob = tmp_path / "clip.mp3"
    blob.write_bytes(payload)
    assert media_hash(blob) == jw_hex(hashlib.sha256(payload).digest())


def test_open_reads_manifest_and_database(builder):
    b = builder("phone.jwlibrary", "Phone", "2026-05-01T00:00:00+0000")
    b.tag("Favorite", type_=0)
    path = b.build()

    with Backup.open(path) as backup:
        assert backup.manifest.device_name == "Phone"
        assert backup.manifest.schema_version == 16
        conn = backup.connect()
        assert conn.execute("SELECT COUNT(*) FROM Tag").fetchone()[0] == 1
        conn.close()


def test_open_rejects_a_non_zip(tmp_path: Path):
    bogus = tmp_path / "not.jwlibrary"
    bogus.write_text("hello")
    with pytest.raises(ArchiveError, match="not a ZIP"):
        Backup.open(bogus)


def test_open_rejects_an_archive_with_no_database(tmp_path: Path):
    path = tmp_path / "empty.jwlibrary"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("something-else.txt", b"")
    with pytest.raises(ArchiveError, match="userData.db"):
        Backup.open(path)


def test_open_rejects_a_database_that_is_not_a_library(tmp_path: Path):
    """A manifest is optional now, so this is what stands between a stray file
    and a merge: the database has to actually be a study library."""
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE unrelated (a)")
    conn.commit()
    conn.close()

    path = tmp_path / "notalibrary.jwlibrary"
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(other, "userData.db")
    with pytest.raises(ArchiveError, match="not a JW Library one"):
        Backup.open(path)


def test_open_rejects_path_traversal(tmp_path: Path):
    path = tmp_path / "evil.jwlibrary"
    manifest = {
        "name": "evil",
        "creationDate": "",
        "version": 1,
        "type": 0,
        "userDataBackup": {
            "schemaVersion": 16,
            "databaseName": "userData.db",
            "deviceName": "x",
            "lastModifiedDate": "",
            "hash": "",
        },
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("userData.db", b"")
        zf.writestr("../escaped.txt", b"nope")
    with pytest.raises(ArchiveError, match="unsafe member path"):
        Backup.open(path)


def test_media_files_excludes_the_database_and_manifest(builder):
    b = builder("phone.jwlibrary", "Phone", "2026-05-01T00:00:00+0000")
    b.media(b"song", "song.mp3")
    with Backup.open(b.build()) as backup:
        names = [p.name for p in backup.media_files()]
        assert len(names) == 1
        assert "userData.db" not in names


def test_write_backup_round_trips(builder, tmp_path: Path):
    b = builder("phone.jwlibrary", "Phone", "2026-05-01T00:00:00+0000")
    b.tag("Favorite", type_=0)
    source = b.build()

    with Backup.open(source) as backup:
        out = tmp_path / "out.jwlibrary"
        media = {
            p.relative_to(backup.workdir).as_posix(): p for p in backup.media_files()
        }
        write_backup(out, backup.db_path, media, backup.manifest)

    with Backup.open(out) as merged:
        assert merged.manifest.name == "out.jwlibrary"
        assert len(merged.manifest.hash) <= 64
        conn = merged.connect()
        assert conn.execute("SELECT COUNT(*) FROM Tag").fetchone()[0] == 1
        conn.close()


@pytest.mark.parametrize(
    "mode,expected",
    [("keep", "0" * 63), ("empty", "")],
)
def test_write_backup_hash_modes(builder, tmp_path: Path, mode: str, expected: str):
    b = builder("phone.jwlibrary", "Phone", "2026-05-01T00:00:00+0000")
    source = b.build()
    with Backup.open(source) as backup:
        out = tmp_path / f"out-{mode}.jwlibrary"
        write_backup(out, backup.db_path, {}, backup.manifest, hash_mode=mode)
    with Backup.open(out) as merged:
        assert merged.manifest.hash == expected


def test_manifest_preserves_unknown_fields():
    raw = {
        "name": "x",
        "creationDate": "",
        "version": 1,
        "type": 0,
        "somethingNew": 42,
        "userDataBackup": {
            "schemaVersion": 16,
            "databaseName": "userData.db",
            "deviceName": "x",
            "lastModifiedDate": "",
            "hash": "",
            "futureField": "keep me",
        },
    }
    manifest = Manifest.parse(raw)
    out = manifest.to_dict()
    assert out["somethingNew"] == 42
    assert out["userDataBackup"]["futureField"] == "keep me"


def test_sqlite_sidecars_are_never_treated_as_media(builder, tmp_path: Path):
    """Reading a row recreates -shm beside the database, because the header
    still says WAL. Anything in media_files ends up inside the merged archive,
    so the sidecars must be excluded by name, not by what was extracted."""
    b = builder("phone.jwlibrary", "Phone", "2026-05-01T00:00:00+0000")
    b.media(b"a song", "song.mp3")
    path = b.build()

    with Backup.open(path) as backup:
        conn = backup.connect(readonly=False)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("SELECT COUNT(*) FROM Location").fetchone()
        conn.commit()
        conn.close()

        names = {p.name for p in backup.media_files()}

    assert not any(n.endswith(("-wal", "-shm", "-journal")) for n in names), names
    assert "userData.db" not in names
    assert len(names) == 1
