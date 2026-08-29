"""Behavioural tests for the merge engine.

Each test builds two small libraries that differ in one specific way, merges
them, and asserts on the resulting database.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from braid.archive import Backup
from braid.merge import MAX_BOOKMARK_SLOT, MergeError, MergeOptions, merge_backups

NEWER = "2026-08-01T00:00:00+0000"
OLDER = "2026-01-01T00:00:00+0000"


def run_merge(base_path: Path, *source_paths: Path, options: MergeOptions | None = None):
    """Merge and hand back an open connection to the result plus the report."""
    stack = [Backup.open(base_path)] + [Backup.open(p) for p in source_paths]
    tmp = tempfile.mkdtemp(prefix="braid-test-")
    try:
        db_path, media, report = merge_backups(
            stack[0], stack[1:], Path(tmp), options
        )
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn, media, report
    finally:
        for backup in stack:
            backup.close()


def scalar(conn: sqlite3.Connection, sql: str, *args):
    row = conn.execute(sql, args).fetchone()
    return row[0] if row else None


# -- tags -------------------------------------------------------------------


def test_identical_tags_collapse_and_new_ones_are_added(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    a.tag("Favorite", type_=0)
    a.tag("sermons")
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    b.tag("Favorite", type_=0)
    b.tag("songs")
    other = b.build()

    conn, _, report = run_merge(base, other)
    names = {r["Name"] for r in conn.execute("SELECT Name FROM Tag")}
    assert names == {"Favorite", "sermons", "songs"}
    assert report.sources[0].added["Tag"] == 1
    assert report.sources[0].reused["Tag"] == 1


def test_same_name_different_type_stays_separate(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    a.tag("study", type_=1)
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    b.tag("study", type_=2)
    other = b.build()

    conn, _, _ = run_merge(base, other)
    assert scalar(conn, "SELECT COUNT(*) FROM Tag") == 2


# -- notes ------------------------------------------------------------------


def test_note_present_on_one_device_only_is_carried_over(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    loc_a = a.location(DocumentId=100, KeySymbol="w26")
    a.note("guid-phone", title="from phone", content="A", location_id=loc_a)
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(DocumentId=200, KeySymbol="w26")
    b.note("guid-tablet", title="from tablet", content="B", location_id=loc_b)
    other = b.build()

    conn, _, _ = run_merge(base, other)
    guids = {r["Guid"] for r in conn.execute("SELECT Guid FROM Note")}
    assert guids == {"guid-phone", "guid-tablet"}


def test_note_edited_on_both_devices_keeps_the_newer_text(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    loc = a.location(DocumentId=100, KeySymbol="w26")
    a.note(
        "shared", title="t", content="old text", location_id=loc,
        last_modified="2026-01-01T00:00:00Z",
    )
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(DocumentId=100, KeySymbol="w26")
    b.note(
        "shared", title="t", content="new text", location_id=loc_b,
        last_modified="2026-06-01T00:00:00Z",
    )
    other = b.build()

    conn, _, report = run_merge(base, other)
    assert scalar(conn, "SELECT COUNT(*) FROM Note") == 1
    assert scalar(conn, "SELECT Content FROM Note") == "new text"
    assert report.sources[0].updated["Note"] == 1
    assert any(c["table"] == "Note" for c in report.sources[0].conflicts)


def test_note_with_an_older_edit_does_not_overwrite_the_base(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    loc = a.location(DocumentId=100, KeySymbol="w26")
    a.note(
        "shared", content="current", location_id=loc,
        last_modified="2026-06-01T00:00:00Z",
    )
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(DocumentId=100, KeySymbol="w26")
    b.note(
        "shared", content="stale", location_id=loc_b,
        last_modified="2026-01-01T00:00:00Z",
    )
    other = b.build()

    conn, _, _ = run_merge(base, other)
    assert scalar(conn, "SELECT Content FROM Note") == "current"


def test_conflicting_notes_with_equal_timestamps_are_reported(builder):
    stamp = "2026-03-03T00:00:00Z"
    a = builder("a.jwlibrary", "Phone", NEWER)
    loc = a.location(DocumentId=1, KeySymbol="w26")
    a.note("shared", content="left", location_id=loc, last_modified=stamp)
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(DocumentId=1, KeySymbol="w26")
    b.note("shared", content="right", location_id=loc_b, last_modified=stamp)
    other = b.build()

    conn, _, report = run_merge(base, other)
    assert scalar(conn, "SELECT Content FROM Note") == "left"
    assert any("both sides carry" in c["detail"] for c in report.sources[0].conflicts)


# -- locations --------------------------------------------------------------


def test_documents_that_differ_only_by_document_id_stay_separate(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    a.location(DocumentId=100, KeySymbol="w26")
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    b.location(DocumentId=101, KeySymbol="w26")
    other = b.build()

    conn, _, _ = run_merge(base, other)
    assert scalar(conn, "SELECT COUNT(*) FROM Location") == 2


def test_the_same_bible_chapter_is_recognised_across_devices(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    a.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty", Type=0)
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    b.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty", Type=0)
    other = b.build()

    conn, _, report = run_merge(base, other)
    assert scalar(conn, "SELECT COUNT(*) FROM Location") == 1
    assert report.sources[0].reused["Location"] == 1


# -- highlights -------------------------------------------------------------


def test_highlights_are_deduplicated_by_guid_and_ranges_follow(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    loc = a.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty")
    mark = a.usermark(loc, "mark-shared", color=1, version=1)
    a.block_range(mark, identifier=1, start=0, end=5)
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty")
    shared = b.usermark(loc_b, "mark-shared", color=1, version=1)
    b.block_range(shared, identifier=1, start=0, end=5)
    fresh = b.usermark(loc_b, "mark-tablet", color=3, version=1)
    b.block_range(fresh, identifier=2, start=7, end=9)
    other = b.build()

    conn, _, _ = run_merge(base, other)
    assert scalar(conn, "SELECT COUNT(*) FROM UserMark") == 2
    assert scalar(conn, "SELECT COUNT(*) FROM BlockRange") == 2


def test_a_newer_highlight_version_replaces_its_ranges(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    loc = a.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty")
    mark = a.usermark(loc, "mark", color=1, version=1)
    a.block_range(mark, identifier=1, start=0, end=5)
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty")
    mark_b = b.usermark(loc_b, "mark", color=6, version=2)
    b.block_range(mark_b, identifier=1, start=0, end=12)
    other = b.build()

    conn, _, report = run_merge(base, other)
    assert scalar(conn, "SELECT ColorIndex FROM UserMark") == 6
    assert scalar(conn, "SELECT EndToken FROM BlockRange") == 12
    assert scalar(conn, "SELECT COUNT(*) FROM BlockRange") == 1
    assert report.sources[0].updated["UserMark"] == 1


# -- bookmarks --------------------------------------------------------------


def test_a_new_bookmark_gets_the_first_free_slot(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    pub = a.location(KeySymbol="w26", Type=1, MepsLanguage=294)
    chap = a.location(DocumentId=10, KeySymbol="w26")
    a.bookmark(pub, chap, slot=0, title="phone bookmark")
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    pub_b = b.location(KeySymbol="w26", Type=1, MepsLanguage=294)
    chap_b = b.location(DocumentId=11, KeySymbol="w26")
    b.bookmark(pub_b, chap_b, slot=0, title="tablet bookmark")
    other = b.build()

    conn, _, _ = run_merge(base, other)
    slots = sorted(r["Slot"] for r in conn.execute("SELECT Slot FROM Bookmark"))
    assert slots == [0, 1]


def test_the_same_bookmark_on_both_devices_is_not_duplicated(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    pub = a.location(KeySymbol="w26", Type=1, MepsLanguage=294)
    chap = a.location(DocumentId=10, KeySymbol="w26")
    a.bookmark(pub, chap, slot=0, title="same place")
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    pub_b = b.location(KeySymbol="w26", Type=1, MepsLanguage=294)
    chap_b = b.location(DocumentId=10, KeySymbol="w26")
    b.bookmark(pub_b, chap_b, slot=3, title="same place")
    other = b.build()

    conn, _, _ = run_merge(base, other)
    assert scalar(conn, "SELECT COUNT(*) FROM Bookmark") == 1


def test_bookmarks_beyond_the_last_slot_are_reported_not_dropped_silently(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    pub = a.location(KeySymbol="w26", Type=1, MepsLanguage=294)
    for slot in range(MAX_BOOKMARK_SLOT + 1):
        chap = a.location(DocumentId=100 + slot, KeySymbol="w26")
        a.bookmark(pub, chap, slot=slot, title=f"b{slot}")
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    pub_b = b.location(KeySymbol="w26", Type=1, MepsLanguage=294)
    chap_b = b.location(DocumentId=999, KeySymbol="w26")
    b.bookmark(pub_b, chap_b, slot=0, title="one too many")
    other = b.build()

    conn, _, report = run_merge(base, other)
    assert scalar(conn, "SELECT COUNT(*) FROM Bookmark") == MAX_BOOKMARK_SLOT + 1
    assert report.sources[0].skipped["Bookmark"] == 1
    assert any("bookmark slots" in c["detail"] for c in report.sources[0].conflicts)


# -- input fields -----------------------------------------------------------


@pytest.mark.parametrize(
    "policy,expected", [("keep", "base answer"), ("overwrite", "other answer")]
)
def test_input_field_conflict_policy(builder, policy: str, expected: str):
    a = builder("a.jwlibrary", "Phone", NEWER)
    loc = a.location(DocumentId=5, KeySymbol="lff")
    a.input_field(loc, "q1", "base answer")
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(DocumentId=5, KeySymbol="lff")
    b.input_field(loc_b, "q1", "other answer")
    other = b.build()

    conn, _, report = run_merge(
        base, other, options=MergeOptions(input_fields=policy)
    )
    assert scalar(conn, "SELECT Value FROM InputField") == expected
    assert any(c["table"] == "InputField" for c in report.sources[0].conflicts)


# -- media and playlists ----------------------------------------------------


def test_identical_media_is_recognised_by_hash_and_not_copied_twice(builder):
    payload = b"the same recording on both devices"

    a = builder("a.jwlibrary", "Phone", NEWER)
    a.media(payload, "song.mp3")
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    b.media(payload, "song.mp3")
    other = b.build()

    conn, media, report = run_merge(base, other)
    assert scalar(conn, "SELECT COUNT(*) FROM IndependentMedia") == 1
    assert report.sources[0].media_reused == 1
    assert report.sources[0].media_added == 0
    assert len(media.members) == 1


def test_different_media_sharing_a_filename_is_renamed_not_overwritten(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    a.media_named(b"phone thumbnail", "default_thumbnail.png")
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    b.media_named(b"tablet thumbnail", "default_thumbnail.png")
    other = b.build()

    conn, media, report = run_merge(base, other)
    assert scalar(conn, "SELECT COUNT(*) FROM IndependentMedia") == 2
    assert len(report.sources[0].media_renamed) == 1
    paths = {r["FilePath"] for r in conn.execute("SELECT FilePath FROM IndependentMedia")}
    assert len(paths) == 2
    assert paths <= set(media.members)


def test_the_same_song_in_two_different_playlists_stays_two_items(builder):
    payload = b"one song"

    a = builder("a.jwlibrary", "Phone", NEWER)
    fp_a = a.media(payload, "song.mp3")
    tag_a = a.tag("Sunday", type_=2)
    item_a = a.playlist_item("Song 1")
    a.playlist_media(item_a, fp_a)
    a.tag_map(tag_a, 0, playlist_item_id=item_a)
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    fp_b = b.media(payload, "song.mp3")
    tag_b = b.tag("Midweek", type_=2)
    item_b = b.playlist_item("Song 1")
    b.playlist_media(item_b, fp_b)
    b.tag_map(tag_b, 0, playlist_item_id=item_b)
    other = b.build()

    conn, _, _ = run_merge(base, other)
    assert scalar(conn, "SELECT COUNT(*) FROM PlaylistItem") == 2
    assert scalar(conn, "SELECT COUNT(*) FROM Tag WHERE Type = 2") == 2
    assert scalar(conn, "SELECT COUNT(*) FROM IndependentMedia") == 1


def test_the_same_playlist_on_both_devices_is_not_duplicated(builder):
    payload = b"one song"

    def make(name, device, stamp):
        x = builder(name, device, stamp)
        fp = x.media(payload, "song.mp3")
        tag = x.tag("Sunday", type_=2)
        item = x.playlist_item("Song 1")
        x.playlist_media(item, fp)
        x.tag_map(tag, 0, playlist_item_id=item)
        return x.build()

    conn, _, _ = run_merge(make("a.jwlibrary", "Phone", NEWER),
                           make("b.jwlibrary", "Tablet", OLDER))
    assert scalar(conn, "SELECT COUNT(*) FROM PlaylistItem") == 1
    assert scalar(conn, "SELECT COUNT(*) FROM TagMap") == 1


def test_tagmap_positions_do_not_collide(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    loc_a1 = a.location(DocumentId=1, KeySymbol="w26")
    loc_a2 = a.location(DocumentId=2, KeySymbol="w26")
    tag_a = a.tag("study")
    a.tag_map(tag_a, 0, location_id=loc_a1)
    a.tag_map(tag_a, 1, location_id=loc_a2)
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(DocumentId=3, KeySymbol="w26")
    tag_b = b.tag("study")
    b.tag_map(tag_b, 0, location_id=loc_b)
    other = b.build()

    conn, _, _ = run_merge(base, other)
    rows = list(conn.execute("SELECT TagId, Position FROM TagMap ORDER BY Position"))
    assert [r["Position"] for r in rows] == [0, 1, 2]
    assert len({(r["TagId"], r["Position"]) for r in rows}) == 3


# -- whole-merge properties -------------------------------------------------


def test_merging_is_idempotent(builder, tmp_path):
    a = builder("a.jwlibrary", "Phone", NEWER)
    loc = a.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty")
    mark = a.usermark(loc, "m1")
    a.block_range(mark)
    a.note("n1", content="hello", location_id=loc, usermark_id=mark)
    tag = a.tag("study")
    a.tag_map(tag, 0, location_id=loc)
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(BookNumber=41, ChapterNumber=2, KeySymbol="nwtsty")
    mark_b = b.usermark(loc_b, "m2")
    b.block_range(mark_b)
    b.note("n2", content="world", location_id=loc_b, usermark_id=mark_b)
    tag_b = b.tag("study")
    b.tag_map(tag_b, 0, location_id=loc_b)
    other = b.build()

    conn, _, report = run_merge(base, other)
    first = report.totals_after
    conn.close()

    # Merging the same source a second time must change nothing.
    conn, _, report2 = run_merge(base, other, other)
    assert report2.totals_after == first
    assert not any(sr.added for sr in report2.sources[1:])


def test_the_merge_leaves_referential_integrity_intact(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    loc = a.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty")
    mark = a.usermark(loc, "m1")
    a.block_range(mark)
    a.note("n1", content="x", location_id=loc, usermark_id=mark)
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(BookNumber=41, ChapterNumber=1, KeySymbol="nwtsty")
    mark_b = b.usermark(loc_b, "m2")
    b.block_range(mark_b)
    b.note("n2", content="y", location_id=loc_b, usermark_id=mark_b)
    other = b.build()

    conn, _, report = run_merge(base, other)
    assert report.integrity_errors == []
    assert list(conn.execute("PRAGMA foreign_key_check")) == []


def test_nothing_is_ever_deleted_from_the_base(builder):
    a = builder("a.jwlibrary", "Phone", NEWER)
    loc = a.location(DocumentId=1, KeySymbol="w26")
    for i in range(5):
        a.note(f"n{i}", content=str(i), location_id=loc)
    base = a.build()

    b = builder("b.jwlibrary", "Tablet", OLDER)
    b.location(DocumentId=2, KeySymbol="w26")
    other = b.build()

    conn, _, _ = run_merge(base, other)
    assert scalar(conn, "SELECT COUNT(*) FROM Note") == 5


def test_a_schema_version_mismatch_is_refused(builder, tmp_path, monkeypatch):
    a = builder("a.jwlibrary", "Phone", NEWER)
    base = a.build()
    b = builder("b.jwlibrary", "Tablet", OLDER)
    other = b.build()

    stack = [Backup.open(base), Backup.open(other)]
    stack[1].manifest.schema_version = 15
    try:
        with pytest.raises(MergeError, match="schema version"):
            merge_backups(stack[0], stack[1:], tmp_path / "work")
    finally:
        for backup in stack:
            backup.close()


def test_the_newest_backup_becomes_the_base(builder):
    a = builder("older.jwlibrary", "Tablet", OLDER)
    a.tag("only-on-tablet")
    older = a.build()

    b = builder("newer.jwlibrary", "Phone", NEWER)
    b.tag("only-on-phone")
    newer = b.build()

    # Order of arguments should not matter; the newer file wins the base slot.
    from braid.cli import _pick_base

    stack = [Backup.open(older), Backup.open(newer)]
    try:
        base, sources = _pick_base(stack)
        assert base.path.name == "newer.jwlibrary"
        assert [s.path.name for s in sources] == ["older.jwlibrary"]
    finally:
        for backup in stack:
            backup.close()
