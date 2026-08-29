"""Tests for the independent post-merge check.

A verifier that always passes is worthless, so half of these tests deliberately
damage a merged file and assert that the check catches it.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest

from jwsync.archive import Backup, write_backup
from jwsync.merge import merge_backups
from jwsync.verify import verify

NEWER = "2026-08-01T00:00:00+0000"
OLDER = "2026-01-01T00:00:00+0000"


def build_pair(builder):
    a = builder("phone.jwlibrary", "Phone", NEWER)
    loc_a = a.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty")
    mark_a = a.usermark(loc_a, "mark-phone")
    a.block_range(mark_a)
    a.note("note-phone", content="from phone", location_id=loc_a)
    a.tag("phone-tag")
    a.input_field(loc_a, "q1", "phone answer")
    pub_a = a.location(KeySymbol="w26", Type=1)
    a.bookmark(pub_a, loc_a, slot=0, title="phone bookmark")
    fp_a = a.media(b"phone song", "phone.mp3")
    tag_pl_a = a.tag("Sunday", type_=2)
    item_a = a.playlist_item("Phone Song")
    a.playlist_media(item_a, fp_a)
    a.tag_map(tag_pl_a, 0, playlist_item_id=item_a)
    phone = a.build()

    b = builder("tablet.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(BookNumber=41, ChapterNumber=2, KeySymbol="nwtsty")
    mark_b = b.usermark(loc_b, "mark-tablet")
    b.block_range(mark_b)
    b.note("note-tablet", content="from tablet", location_id=loc_b)
    b.tag("tablet-tag")
    b.input_field(loc_b, "q2", "tablet answer")
    fp_b = b.media(b"tablet song", "tablet.mp3")
    tag_pl_b = b.tag("Midweek", type_=2)
    item_b = b.playlist_item("Tablet Song")
    b.playlist_media(item_b, fp_b)
    b.tag_map(tag_pl_b, 0, playlist_item_id=item_b)
    tablet = b.build()

    return phone, tablet


def do_merge(phone: Path, tablet: Path, out: Path) -> Path:
    stack = [Backup.open(phone), Backup.open(tablet)]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db_path, media, _ = merge_backups(stack[0], stack[1:], Path(tmp))
            write_backup(out, db_path, media.members, stack[0].manifest)
    finally:
        for backup in stack:
            backup.close()
    return out


def repack(path: Path, mutate) -> Path:
    """Unpack a .jwlibrary, run ``mutate`` on its database, pack it back."""
    work = path.parent / f".repack-{path.stem}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    with zipfile.ZipFile(path) as zf:
        zf.extractall(work)
    conn = sqlite3.connect(work / "userData.db")
    mutate(conn)
    conn.commit()
    conn.close()
    damaged = path.with_name(f"damaged-{path.name}")
    with zipfile.ZipFile(damaged, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(work.rglob("*")):
            if entry.is_file():
                zf.write(entry, entry.relative_to(work).as_posix())
    return damaged


def test_a_good_merge_passes(builder, tmp_path):
    phone, tablet = build_pair(builder)
    merged = do_merge(phone, tablet, tmp_path / "merged.jwlibrary")

    result = verify(merged, [phone, tablet])
    assert result.ok, result.to_text()
    assert result.checked["Note"] == 2
    assert result.checked["UserMark"] == 2
    assert result.checked["PlaylistItem"] == 2
    assert result.checked["Bookmark"] == 1
    assert result.checked["InputField"] == 2


@pytest.mark.parametrize(
    "table,sql,expected_table",
    [
        ("Note", "DELETE FROM Note WHERE Guid = 'note-tablet'", "Note"),
        (
            "UserMark",
            "DELETE FROM BlockRange WHERE UserMarkId IN"
            " (SELECT UserMarkId FROM UserMark WHERE UserMarkGuid = 'mark-tablet');"
            " DELETE FROM UserMark WHERE UserMarkGuid = 'mark-tablet'",
            "UserMark",
        ),
        (
            "Tag",
            "DELETE FROM TagMap WHERE TagId IN"
            " (SELECT TagId FROM Tag WHERE Name = 'tablet-tag');"
            " DELETE FROM Tag WHERE Name = 'tablet-tag'",
            "Tag",
        ),
        ("Bookmark", "DELETE FROM Bookmark", "Bookmark"),
        ("InputField", "DELETE FROM InputField WHERE TextTag = 'q2'", "InputField"),
    ],
)
def test_a_dropped_item_is_caught(builder, tmp_path, table, sql, expected_table):
    phone, tablet = build_pair(builder)
    merged = do_merge(phone, tablet, tmp_path / "merged.jwlibrary")
    damaged = repack(merged, lambda c: c.executescript(sql))

    result = verify(damaged, [phone, tablet])
    assert not result.ok
    assert any(m.table == expected_table for m in result.missing), result.to_text()


def test_a_dropped_playlist_item_is_caught(builder, tmp_path):
    phone, tablet = build_pair(builder)
    merged = do_merge(phone, tablet, tmp_path / "merged.jwlibrary")

    def mutate(conn):
        conn.executescript(
            "DELETE FROM TagMap WHERE PlaylistItemId IN"
            " (SELECT PlaylistItemId FROM PlaylistItem WHERE Label = 'Tablet Song');"
            " DELETE FROM PlaylistItemIndependentMediaMap WHERE PlaylistItemId IN"
            " (SELECT PlaylistItemId FROM PlaylistItem WHERE Label = 'Tablet Song');"
            " DELETE FROM PlaylistItem WHERE Label = 'Tablet Song'"
        )

    result = verify(repack(merged, mutate), [phone, tablet])
    assert not result.ok
    assert any(m.table == "PlaylistItem" for m in result.missing)


def test_a_media_file_missing_from_the_archive_is_caught(builder, tmp_path):
    phone, tablet = build_pair(builder)
    merged = do_merge(phone, tablet, tmp_path / "merged.jwlibrary")

    # Rebuild the archive without one of the media blobs.
    stripped = tmp_path / "stripped.jwlibrary"
    with zipfile.ZipFile(merged) as src, zipfile.ZipFile(
        stripped, "w", zipfile.ZIP_DEFLATED
    ) as dst:
        dropped = False
        for item in src.infolist():
            if (
                not dropped
                and item.filename not in ("userData.db", "manifest.json")
            ):
                dropped = True
                continue
            dst.writestr(item, src.read(item.filename))

    result = verify(stripped, [phone, tablet])
    assert not result.ok
    assert result.media_missing_files


def test_verify_reports_which_source_an_item_came_from(builder, tmp_path):
    phone, tablet = build_pair(builder)
    merged = do_merge(phone, tablet, tmp_path / "merged.jwlibrary")
    damaged = repack(
        merged, lambda c: c.execute("DELETE FROM Note WHERE Guid = 'note-tablet'")
    )

    result = verify(damaged, [phone, tablet])
    detail = " ".join(m.description for m in result.missing)
    assert "tablet.jwlibrary" in detail
