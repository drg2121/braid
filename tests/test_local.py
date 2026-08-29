"""Tests for reading and writing a JW Library installed on this computer.

A fake library folder stands in for the real app: the same userData.db laid out
the same way, so the safety rules can be exercised without touching anyone's
actual study data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from braid.archive import Backup
from braid.local import (
    DB_NAME,
    LocalLibrary,
    LocalLibraryError,
    find_libraries,
)

NEWER = "2026-08-01T00:00:00+0000"
OLDER = "2026-01-01T00:00:00+0000"


@pytest.fixture
def local_library(builder, tmp_path):
    """A folder laid out the way JW Library lays out its own."""

    def make(tag: str = "on-this-computer", with_media: bool = True) -> LocalLibrary:
        b = builder("seed.jwlibrary", "Computer", NEWER)
        loc = b.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty")
        mark = b.usermark(loc, "mark-computer")
        b.block_range(mark)
        b.note("note-computer", content="written on the laptop", location_id=loc)
        b.tag(tag)
        if with_media:
            fp = b.media(b"a song on the laptop", "laptop.mp3")
            pl = b.tag("Laptop playlist", type_=2)
            item = b.playlist_item("Laptop Song")
            b.playlist_media(item, fp)
            b.tag_map(pl, 0, playlist_item_id=item)
        seed = b.build()

        folder = tmp_path / "Userdata"
        folder.mkdir(exist_ok=True)
        with Backup.open(seed) as backup:
            (folder / DB_NAME).write_bytes(backup.db_path.read_bytes())
            for entry in backup.media_files():
                name = entry.relative_to(backup.workdir).as_posix()
                (folder / name).write_bytes(entry.read_bytes())
        return LocalLibrary(folder)

    return make


# -- reading ---------------------------------------------------------------


def test_a_library_folder_is_recognised(local_library):
    library = local_library()
    assert library.exists()
    assert library.schema_version() == 0 or library.schema_version() >= 0
    assert library.counts()["Note"] == 1


def test_export_produces_a_normal_backup_archive(local_library, tmp_path):
    library = local_library()
    out = library.export(tmp_path / "exported.jwlibrary", device_name="Laptop")

    with Backup.open(out) as backup:
        assert backup.manifest.device_name == "Laptop"
        assert backup.manifest.database_name == DB_NAME
        conn = backup.connect()
        assert conn.execute("SELECT COUNT(*) FROM Note").fetchone()[0] == 1
        names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
        conn.close()
    assert "on-this-computer" in names


def test_export_carries_the_media_the_database_references(local_library, tmp_path):
    library = local_library()
    out = library.export(tmp_path / "exported.jwlibrary")

    with Backup.open(out) as backup:
        conn = backup.connect()
        refs = {r[0] for r in conn.execute("SELECT FilePath FROM IndependentMedia")}
        conn.close()
        present = {
            p.relative_to(backup.workdir).as_posix() for p in backup.media_files()
        }
    assert refs
    assert refs <= present


def test_export_folds_in_the_write_ahead_log(local_library, tmp_path):
    """The real app runs in WAL mode, where the main file can be nearly empty."""
    library = local_library()
    conn = sqlite3.connect(library.db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("INSERT INTO Tag(Type, Name) VALUES (1, 'only-in-the-wal')")
    conn.commit()
    # Leave the WAL in place, exactly as a running app would.
    conn.close()

    out = library.export(tmp_path / "exported.jwlibrary")
    with Backup.open(out) as backup:
        c = backup.connect()
        names = {r[0] for r in c.execute("SELECT Name FROM Tag")}
        c.close()
    assert "only-in-the-wal" in names


# -- writing ---------------------------------------------------------------


def test_install_refuses_while_the_app_is_running(local_library, tmp_path, monkeypatch):
    library = local_library()
    exported = library.export(tmp_path / "exported.jwlibrary")
    monkeypatch.setattr("braid.local.jw_library_is_running", lambda: True)

    with pytest.raises(LocalLibraryError, match="running"):
        library.install(exported)


def test_install_copies_the_old_library_aside_first(
    builder, local_library, tmp_path, monkeypatch
):
    monkeypatch.setattr("braid.local.jw_library_is_running", lambda: False)
    library = local_library()

    other = builder("phone.jwlibrary", "Phone", OLDER)
    other.tag("from-the-phone")
    incoming = other.build()

    safety = tmp_path / "safety"
    result = library.install(incoming, safety_dir=safety)

    saved = Path(result["safetyCopy"])
    assert saved.is_dir()
    assert (saved / DB_NAME).is_file()

    # The saved copy still holds what the library had before.
    conn = sqlite3.connect(f"file:{saved / DB_NAME}?mode=ro", uri=True)
    names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
    conn.close()
    assert "on-this-computer" in names


def test_install_replaces_the_database_and_adds_media(
    builder, local_library, tmp_path, monkeypatch
):
    monkeypatch.setattr("braid.local.jw_library_is_running", lambda: False)
    library = local_library()

    other = builder("merged.jwlibrary", "Merged", NEWER)
    other.tag("from-the-phone")
    other.media(b"a song from the phone", "phone.mp3")
    incoming = other.build()

    result = library.install(incoming, safety_dir=tmp_path / "safety")

    conn = sqlite3.connect(f"file:{library.db_path}?mode=ro", uri=True)
    names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
    paths = {r[0] for r in conn.execute("SELECT FilePath FROM IndependentMedia")}
    conn.close()

    assert "from-the-phone" in names
    assert result["mediaCopied"] >= 1
    for path in paths:
        assert (library.path / path).is_file(), f"{path} was not copied in"


def test_install_leaves_no_stale_write_ahead_log(
    builder, local_library, tmp_path, monkeypatch
):
    monkeypatch.setattr("braid.local.jw_library_is_running", lambda: False)
    library = local_library()

    # SQLite removes the WAL on a clean close, so write the sidecars a crashed
    # app would have left behind. If install did not delete them, SQLite would
    # replay them over the database we are putting in place.
    stale_wal = library.db_path.with_name(DB_NAME + "-wal")
    stale_shm = library.db_path.with_name(DB_NAME + "-shm")
    stale_wal.write_bytes(b"\x00" * 64)
    stale_shm.write_bytes(b"\x00" * 64)
    assert stale_wal.exists() and stale_shm.exists()

    other = builder("merged.jwlibrary", "Merged", NEWER)
    other.tag("the-new-truth")
    library.install(other.build(), safety_dir=tmp_path / "safety")

    assert not stale_wal.exists()
    assert not stale_shm.exists()
    conn = sqlite3.connect(f"file:{library.db_path}?mode=ro", uri=True)
    names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
    conn.close()
    assert names == {"the-new-truth"}


def test_install_on_an_empty_folder_is_refused(tmp_path):
    library = LocalLibrary(tmp_path / "nothing-here")
    with pytest.raises(LocalLibraryError, match="no userData.db"):
        library.install(tmp_path / "whatever.jwlibrary")


def test_a_full_round_trip_keeps_everything(
    builder, local_library, tmp_path, monkeypatch
):
    """pull, merge with a phone backup, push -- nothing lost at either end."""
    from braid.archive import write_backup
    from braid.merge import merge_backups
    from braid.verify import verify

    monkeypatch.setattr("braid.local.jw_library_is_running", lambda: False)
    library = local_library()

    pulled = library.export(tmp_path / "laptop.jwlibrary", device_name="Laptop")

    phone = builder("phone.jwlibrary", "Phone", OLDER)
    loc = phone.location(BookNumber=43, ChapterNumber=3, KeySymbol="nwtsty")
    phone.note("note-phone", content="written on the phone", location_id=loc)
    phone.tag("from-the-phone")
    phone_path = phone.build()

    stack = [Backup.open(pulled), Backup.open(phone_path)]
    merged_path = tmp_path / "merged.jwlibrary"
    try:
        db_path, media, _ = merge_backups(stack[0], stack[1:], tmp_path / "work")
        write_backup(merged_path, db_path, media.members, stack[0].manifest)
    finally:
        for backup in stack:
            backup.close()

    assert verify(merged_path, [pulled, phone_path]).ok

    library.install(merged_path, safety_dir=tmp_path / "safety")

    conn = sqlite3.connect(f"file:{library.db_path}?mode=ro", uri=True)
    guids = {r[0] for r in conn.execute("SELECT Guid FROM Note")}
    names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
    conn.close()
    assert guids == {"note-computer", "note-phone"}
    assert {"on-this-computer", "from-the-phone"} <= names


# -- discovery -------------------------------------------------------------


def test_discovery_returns_only_folders_that_hold_a_database(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr("braid.local._macos_candidates", lambda: [empty])
    monkeypatch.setattr("braid.local.platform.system", lambda: "Darwin")
    assert find_libraries() == []


def test_discovery_on_an_unsupported_platform_is_empty(monkeypatch):
    monkeypatch.setattr("braid.local.platform.system", lambda: "Linux")
    assert find_libraries() == []
