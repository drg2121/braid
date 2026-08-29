"""Merge engine for JW Library ``userData.db`` databases.

The merge is *additive and idempotent*: merging the same source twice adds
nothing the second time. Every table is keyed on the identity JW Library
itself uses -- a GUID where one exists, otherwise the natural key behind the
table's UNIQUE constraints -- so rows that describe the same note, highlight,
tag or playlist item collapse into one instead of being duplicated.

Nothing is ever deleted. A merge can only add rows, or update a row whose
counterpart in the source is demonstrably newer.
"""

from __future__ import annotations

import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .archive import Backup
from .report import MergeReport, SourceReport

#: Highest bookmark slot JW Library exposes per publication.
MAX_BOOKMARK_SLOT = 9

COUNTED_TABLES = (
    "Location",
    "UserMark",
    "BlockRange",
    "Note",
    "Bookmark",
    "InputField",
    "Tag",
    "TagMap",
    "IndependentMedia",
    "PlaylistItem",
    "PlaylistItemAccuracy",
    "PlaylistItemIndependentMediaMap",
    "PlaylistItemLocationMap",
    "PlaylistItemMarker",
    "PlaylistItemMarkerBibleVerseMap",
    "PlaylistItemMarkerParagraphMap",
)

_SENTINEL = "\x00NULL\x00"


def _k(*values: object) -> tuple:
    """Build a hashable identity key that treats NULL as a distinct value."""
    return tuple(_SENTINEL if v is None else v for v in values)


class MergeError(RuntimeError):
    """Raised when a merge cannot proceed."""


@dataclass
class MergeOptions:
    """Policies that decide how ambiguous cases are resolved."""

    #: ``keep`` leaves the target value in place, ``overwrite`` takes the
    #: source value, for InputField rows that differ and carry no timestamp.
    input_fields: str = "keep"
    #: Enforce foreign keys while merging and verify them afterwards.
    check_integrity: bool = True


@dataclass
class MediaPlan:
    """Archive members that must end up in the merged ``.jwlibrary``."""

    members: dict[str, Path] = field(default_factory=dict)

    def add(self, member: str, source: Path) -> None:
        self.members[member] = source


class Merger:
    """Merges source databases into a target database opened for writing."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        media: MediaPlan,
        options: MergeOptions | None = None,
    ) -> None:
        self.conn = conn
        self.media = media
        self.options = options or MergeOptions()
        self.conn.row_factory = sqlite3.Row
        if self.options.check_integrity:
            self.conn.execute("PRAGMA foreign_keys = ON")

    # -- small helpers --------------------------------------------------

    def _rows(self, conn: sqlite3.Connection, sql: str, *args: object):
        return conn.execute(sql, args).fetchall()

    def _scalar(self, sql: str, *args: object):
        row = self.conn.execute(sql, args).fetchone()
        return row[0] if row else None

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in COUNTED_TABLES:
            try:
                out[table] = self.conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            except sqlite3.OperationalError:
                continue
        return out

    # -- entry point ----------------------------------------------------

    def merge_backup(self, source: Backup, report: MergeReport) -> SourceReport:
        sr = report.add_source(
            name=source.path.name,
            device=source.manifest.device_name,
            last_modified=source.manifest.last_modified_date,
        )
        src = source.connect(readonly=True)
        try:
            self._merge_db(src, source, sr)
        finally:
            src.close()
        return sr

    def _merge_db(
        self, src: sqlite3.Connection, backup: Backup, sr: SourceReport
    ) -> None:
        src.row_factory = sqlite3.Row
        self._merge_migrations(src)
        accuracy = self._merge_accuracy(src, sr)
        locations = self._merge_locations(src, sr)
        media_ids, media_paths = self._merge_media(src, backup, sr)
        marks = self._merge_usermarks(src, locations, sr)
        self._merge_notes(src, marks, locations, sr)
        self._merge_bookmarks(src, locations, sr)
        self._merge_input_fields(src, locations, sr)
        tags = self._merge_tags(src, sr)
        items = self._merge_playlist_items(
            src, tags, accuracy, media_ids, media_paths, locations, sr
        )
        self._merge_playlist_children(src, items, media_ids, locations, sr)
        self._merge_tagmaps(src, tags, items, locations, sr)
        self.conn.commit()

    # -- grdb_migrations -------------------------------------------------

    def _merge_migrations(self, src: sqlite3.Connection) -> None:
        for row in self._rows(src, "SELECT identifier FROM grdb_migrations"):
            self.conn.execute(
                "INSERT OR IGNORE INTO grdb_migrations(identifier) VALUES (?)",
                (row["identifier"],),
            )

    # -- PlaylistItemAccuracy --------------------------------------------

    def _merge_accuracy(
        self, src: sqlite3.Connection, sr: SourceReport
    ) -> dict[int, int]:
        index = {
            r["Description"]: r["PlaylistItemAccuracyId"]
            for r in self.conn.execute(
                "SELECT PlaylistItemAccuracyId, Description FROM PlaylistItemAccuracy"
            )
        }
        mapping: dict[int, int] = {}
        for row in self._rows(
            src, "SELECT PlaylistItemAccuracyId, Description FROM PlaylistItemAccuracy"
        ):
            desc = row["Description"]
            if desc in index:
                mapping[row["PlaylistItemAccuracyId"]] = index[desc]
                sr.reused["PlaylistItemAccuracy"] += 1
                continue
            cur = self.conn.execute(
                "INSERT INTO PlaylistItemAccuracy(Description) VALUES (?)", (desc,)
            )
            index[desc] = cur.lastrowid
            mapping[row["PlaylistItemAccuracyId"]] = cur.lastrowid
            sr.added["PlaylistItemAccuracy"] += 1
        return mapping

    # -- Location ---------------------------------------------------------

    _LOCATION_COLUMNS = (
        "BookNumber",
        "ChapterNumber",
        "DocumentId",
        "Track",
        "IssueTagNumber",
        "KeySymbol",
        "MepsLanguage",
        "Type",
        "Title",
        "Specialty",
        "Edition",
    )

    @staticmethod
    def _location_identity(row: sqlite3.Row) -> tuple:
        """Full natural identity -- everything except the id and the title."""
        return _k(
            row["BookNumber"],
            row["ChapterNumber"],
            row["DocumentId"],
            row["Track"],
            row["IssueTagNumber"],
            row["KeySymbol"],
            row["MepsLanguage"],
            row["Type"],
            row["Specialty"],
            row["Edition"],
        )

    @staticmethod
    def _location_unique_key(row: sqlite3.Row) -> tuple | None:
        """The table's ``UNIQUE`` constraint, or None when SQLite would not
        enforce it because a component is NULL."""
        parts = (
            row["BookNumber"],
            row["ChapterNumber"],
            row["KeySymbol"],
            row["MepsLanguage"],
            row["Type"],
        )
        return None if any(p is None for p in parts) else parts

    @staticmethod
    def _location_media_key(row: sqlite3.Row) -> tuple | None:
        """The ``IX_Location_Media`` unique index, or None when NULLs make
        SQLite treat the row as distinct."""
        parts = (
            row["KeySymbol"],
            row["IssueTagNumber"],
            row["MepsLanguage"],
            row["DocumentId"],
            row["Track"],
            row["Type"],
        )
        if any(p is None for p in parts):
            return None
        return parts + (row["Specialty"] or "", row["Edition"] or "")

    def _merge_locations(
        self, src: sqlite3.Connection, sr: SourceReport
    ) -> dict[int, int]:
        by_identity: dict[tuple, int] = {}
        by_unique: dict[tuple, int] = {}
        by_media: dict[tuple, int] = {}
        for row in self.conn.execute("SELECT * FROM Location"):
            lid = row["LocationId"]
            by_identity[self._location_identity(row)] = lid
            if (k1 := self._location_unique_key(row)) is not None:
                by_unique.setdefault(k1, lid)
            if (k2 := self._location_media_key(row)) is not None:
                by_media.setdefault(k2, lid)

        mapping: dict[int, int] = {}
        cols = ", ".join(self._LOCATION_COLUMNS)
        holes = ", ".join("?" for _ in self._LOCATION_COLUMNS)

        for row in self._rows(src, "SELECT * FROM Location"):
            src_id = row["LocationId"]
            identity = self._location_identity(row)
            if (hit := by_identity.get(identity)) is not None:
                mapping[src_id] = hit
                sr.reused["Location"] += 1
                continue

            k1 = self._location_unique_key(row)
            k2 = self._location_media_key(row)
            clash = (by_unique.get(k1) if k1 else None) or (
                by_media.get(k2) if k2 else None
            )
            if clash is not None:
                # Same publication position, cosmetic differences elsewhere.
                mapping[src_id] = clash
                sr.reused["Location"] += 1
                sr.conflict(
                    "Location",
                    f"source LocationId {src_id} ({row['KeySymbol']!r}) collides with "
                    f"target LocationId {clash} on a UNIQUE key",
                    "mapped onto the existing location",
                )
                continue

            cur = self.conn.execute(
                f"INSERT INTO Location({cols}) VALUES ({holes})",
                tuple(row[c] for c in self._LOCATION_COLUMNS),
            )
            new_id = cur.lastrowid
            mapping[src_id] = new_id
            by_identity[identity] = new_id
            if k1 is not None:
                by_unique.setdefault(k1, new_id)
            if k2 is not None:
                by_media.setdefault(k2, new_id)
            sr.added["Location"] += 1

        return mapping

    # -- IndependentMedia -------------------------------------------------

    def _merge_media(
        self, src: sqlite3.Connection, backup: Backup, sr: SourceReport
    ) -> tuple[dict[int, int], dict[str, str]]:
        """Returns (IndependentMediaId map, FilePath map)."""
        by_hash: dict[str, sqlite3.Row] = {}
        taken_paths: set[str] = set()
        for row in self.conn.execute("SELECT * FROM IndependentMedia"):
            by_hash.setdefault(row["Hash"], row)
            taken_paths.add(row["FilePath"])

        id_map: dict[int, int] = {}
        path_map: dict[str, str] = {}

        for row in self._rows(src, "SELECT * FROM IndependentMedia"):
            src_id = row["IndependentMediaId"]
            src_path = row["FilePath"]
            existing = by_hash.get(row["Hash"])
            if existing is not None:
                id_map[src_id] = existing["IndependentMediaId"]
                path_map[src_path] = existing["FilePath"]
                sr.media_reused += 1
                sr.reused["IndependentMedia"] += 1
                continue

            blob = backup.workdir / src_path
            member = src_path
            if member in taken_paths or member in self.media.members:
                member = f"{uuid.uuid4()}{Path(src_path).suffix}"
                sr.media_renamed.append((src_path, member))

            cur = self.conn.execute(
                "INSERT INTO IndependentMedia"
                "(OriginalFilename, FilePath, MimeType, Hash) VALUES (?, ?, ?, ?)",
                (row["OriginalFilename"], member, row["MimeType"], row["Hash"]),
            )
            new_id = cur.lastrowid
            id_map[src_id] = new_id
            path_map[src_path] = member
            taken_paths.add(member)
            by_hash[row["Hash"]] = self.conn.execute(
                "SELECT * FROM IndependentMedia WHERE IndependentMediaId = ?", (new_id,)
            ).fetchone()

            if blob.is_file():
                self.media.add(member, blob)
                sr.media_added += 1
            else:
                sr.skipped["IndependentMediaFile"] += 1
                sr.conflict(
                    "IndependentMedia",
                    f"{src_path} is referenced by the database but is not"
                    " in the archive",
                    "row kept, file missing",
                )

        return id_map, path_map

    # -- UserMark / BlockRange --------------------------------------------

    def _merge_usermarks(
        self, src: sqlite3.Connection, locations: dict[int, int], sr: SourceReport
    ) -> dict[int, int]:
        index = {
            r["UserMarkGuid"]: r
            for r in self.conn.execute("SELECT * FROM UserMark")
        }
        mapping: dict[int, int] = {}

        for row in self._rows(src, "SELECT * FROM UserMark"):
            src_id = row["UserMarkId"]
            guid = row["UserMarkGuid"]
            loc = locations.get(row["LocationId"])
            if loc is None:
                sr.skipped["UserMark"] += 1
                continue

            existing = index.get(guid)
            if existing is None:
                cur = self.conn.execute(
                    "INSERT INTO UserMark"
                    "(ColorIndex, LocationId, StyleIndex, UserMarkGuid, Version)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        row["ColorIndex"],
                        loc,
                        row["StyleIndex"],
                        guid,
                        row["Version"],
                    ),
                )
                new_id = cur.lastrowid
                mapping[src_id] = new_id
                index[guid] = self.conn.execute(
                    "SELECT * FROM UserMark WHERE UserMarkId = ?", (new_id,)
                ).fetchone()
                sr.added["UserMark"] += 1
                self._copy_block_ranges(src, src_id, new_id, sr)
                continue

            target_id = existing["UserMarkId"]
            mapping[src_id] = target_id
            if (row["Version"] or 0) > (existing["Version"] or 0):
                self.conn.execute(
                    "UPDATE UserMark SET ColorIndex = ?, StyleIndex = ?,"
                    " LocationId = ?, Version = ? WHERE UserMarkId = ?",
                    (
                        row["ColorIndex"],
                        row["StyleIndex"],
                        loc,
                        row["Version"],
                        target_id,
                    ),
                )
                self.conn.execute(
                    "DELETE FROM BlockRange WHERE UserMarkId = ?", (target_id,)
                )
                self._copy_block_ranges(src, src_id, target_id, sr)
                sr.updated["UserMark"] += 1
            else:
                sr.reused["UserMark"] += 1
                self._copy_block_ranges(src, src_id, target_id, sr, additive=True)

        return mapping

    def _copy_block_ranges(
        self,
        src: sqlite3.Connection,
        src_mark: int,
        target_mark: int,
        sr: SourceReport,
        *,
        additive: bool = False,
    ) -> None:
        existing: set[tuple] = set()
        if additive:
            existing = {
                _k(r["BlockType"], r["Identifier"], r["StartToken"], r["EndToken"])
                for r in self.conn.execute(
                    "SELECT * FROM BlockRange WHERE UserMarkId = ?", (target_mark,)
                )
            }
        for row in self._rows(
            src, "SELECT * FROM BlockRange WHERE UserMarkId = ?", src_mark
        ):
            key = _k(
                row["BlockType"], row["Identifier"], row["StartToken"], row["EndToken"]
            )
            if key in existing:
                sr.reused["BlockRange"] += 1
                continue
            self.conn.execute(
                "INSERT INTO BlockRange"
                "(BlockType, Identifier, StartToken, EndToken, UserMarkId)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    row["BlockType"],
                    row["Identifier"],
                    row["StartToken"],
                    row["EndToken"],
                    target_mark,
                ),
            )
            existing.add(key)
            sr.added["BlockRange"] += 1

    # -- Note --------------------------------------------------------------

    def _merge_notes(
        self,
        src: sqlite3.Connection,
        marks: dict[int, int],
        locations: dict[int, int],
        sr: SourceReport,
    ) -> dict[int, int]:
        index = {r["Guid"]: r for r in self.conn.execute("SELECT * FROM Note")}
        mapping: dict[int, int] = {}

        for row in self._rows(src, "SELECT * FROM Note"):
            src_id = row["NoteId"]
            guid = row["Guid"]
            mark = marks.get(row["UserMarkId"]) if row["UserMarkId"] else None
            loc = locations.get(row["LocationId"]) if row["LocationId"] else None
            existing = index.get(guid)

            if existing is None:
                cur = self.conn.execute(
                    "INSERT INTO Note(Guid, UserMarkId, LocationId, Title, Content,"
                    " LastModified, Created, BlockType, BlockIdentifier)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        guid,
                        mark,
                        loc,
                        row["Title"],
                        row["Content"],
                        row["LastModified"],
                        row["Created"],
                        row["BlockType"],
                        row["BlockIdentifier"],
                    ),
                )
                mapping[src_id] = cur.lastrowid
                index[guid] = self.conn.execute(
                    "SELECT * FROM Note WHERE NoteId = ?", (cur.lastrowid,)
                ).fetchone()
                sr.added["Note"] += 1
                continue

            target_id = existing["NoteId"]
            mapping[src_id] = target_id
            src_mod = row["LastModified"] or ""
            tgt_mod = existing["LastModified"] or ""
            same = (row["Title"] or "") == (existing["Title"] or "") and (
                row["Content"] or ""
            ) == (existing["Content"] or "")

            if same or src_mod <= tgt_mod:
                sr.reused["Note"] += 1
                if not same and src_mod == tgt_mod:
                    sr.conflict(
                        "Note",
                        f"note {guid} differs but both sides carry"
                        f" LastModified {src_mod}",
                        "kept the copy already in the target",
                    )
                continue

            self.conn.execute(
                "UPDATE Note SET UserMarkId = ?, LocationId = ?, Title = ?,"
                " Content = ?, LastModified = ?, BlockType = ?, BlockIdentifier = ?"
                " WHERE NoteId = ?",
                (
                    mark,
                    loc,
                    row["Title"],
                    row["Content"],
                    src_mod,
                    row["BlockType"],
                    row["BlockIdentifier"],
                    target_id,
                ),
            )
            sr.updated["Note"] += 1
            sr.conflict(
                "Note",
                f"note {guid} edited on both sides ({tgt_mod} vs {src_mod})",
                "took the newer copy from the source",
            )

        return mapping

    # -- Bookmark ----------------------------------------------------------

    def _merge_bookmarks(
        self, src: sqlite3.Connection, locations: dict[int, int], sr: SourceReport
    ) -> None:
        rows = list(self.conn.execute("SELECT * FROM Bookmark"))
        index = {
            _k(
                r["PublicationLocationId"],
                r["LocationId"],
                r["BlockType"],
                r["BlockIdentifier"],
            )
            for r in rows
        }
        used_slots: dict[int, set[int]] = {}
        for r in rows:
            used_slots.setdefault(r["PublicationLocationId"], set()).add(r["Slot"])

        for row in self._rows(src, "SELECT * FROM Bookmark"):
            pub = locations.get(row["PublicationLocationId"])
            loc = locations.get(row["LocationId"])
            if pub is None or loc is None:
                sr.skipped["Bookmark"] += 1
                continue

            key = _k(pub, loc, row["BlockType"], row["BlockIdentifier"])
            if key in index:
                sr.reused["Bookmark"] += 1
                continue

            slots = used_slots.setdefault(pub, set())
            slot = next(
                (s for s in range(MAX_BOOKMARK_SLOT + 1) if s not in slots), None
            )
            if slot is None:
                sr.skipped["Bookmark"] += 1
                sr.conflict(
                    "Bookmark",
                    f"publication location {pub} already uses all "
                    f"{MAX_BOOKMARK_SLOT + 1} bookmark slots",
                    f"dropped {row['Title']!r}",
                )
                continue

            self.conn.execute(
                "INSERT INTO Bookmark(LocationId, PublicationLocationId, Slot, Title,"
                " Snippet, BlockType, BlockIdentifier) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    loc,
                    pub,
                    slot,
                    row["Title"],
                    row["Snippet"],
                    row["BlockType"],
                    row["BlockIdentifier"],
                ),
            )
            slots.add(slot)
            index.add(key)
            sr.added["Bookmark"] += 1

    # -- InputField --------------------------------------------------------

    def _merge_input_fields(
        self, src: sqlite3.Connection, locations: dict[int, int], sr: SourceReport
    ) -> None:
        index = {
            _k(r["LocationId"], r["TextTag"]): r["Value"]
            for r in self.conn.execute("SELECT * FROM InputField")
        }
        for row in self._rows(src, "SELECT * FROM InputField"):
            loc = locations.get(row["LocationId"])
            if loc is None:
                sr.skipped["InputField"] += 1
                continue
            key = _k(loc, row["TextTag"])
            if key not in index:
                self.conn.execute(
                    "INSERT INTO InputField(LocationId, TextTag, Value)"
                    " VALUES (?, ?, ?)",
                    (loc, row["TextTag"], row["Value"]),
                )
                index[key] = row["Value"]
                sr.added["InputField"] += 1
                continue

            if index[key] == row["Value"]:
                sr.reused["InputField"] += 1
                continue

            if self.options.input_fields == "overwrite":
                self.conn.execute(
                    "UPDATE InputField SET Value = ?"
                    " WHERE LocationId = ? AND TextTag = ?",
                    (row["Value"], loc, row["TextTag"]),
                )
                index[key] = row["Value"]
                sr.updated["InputField"] += 1
                resolution = "took the source value (--input-fields overwrite)"
            else:
                sr.reused["InputField"] += 1
                resolution = "kept the target value (--input-fields keep)"

            sr.conflict(
                "InputField",
                f"field {row['TextTag']!r} at location {loc} has two different answers"
                " and the schema records no timestamp",
                resolution,
            )

    # -- Tag ---------------------------------------------------------------

    def _merge_tags(self, src: sqlite3.Connection, sr: SourceReport) -> dict[int, int]:
        index = {
            (r["Type"], r["Name"]): r["TagId"]
            for r in self.conn.execute("SELECT * FROM Tag")
        }
        mapping: dict[int, int] = {}
        for row in self._rows(src, "SELECT * FROM Tag"):
            key = (row["Type"], row["Name"])
            if key in index:
                mapping[row["TagId"]] = index[key]
                sr.reused["Tag"] += 1
                continue
            cur = self.conn.execute(
                "INSERT INTO Tag(Type, Name) VALUES (?, ?)", key
            )
            index[key] = cur.lastrowid
            mapping[row["TagId"]] = cur.lastrowid
            sr.added["Tag"] += 1
        return mapping

    # -- PlaylistItem -------------------------------------------------------

    @staticmethod
    def _playlist_item_key(
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        owning_tag: tuple | None,
        *,
        media_hash_by_id: dict[int, str],
        media_hash_by_path: dict[str, str],
        location_key: dict[int, tuple],
    ) -> tuple:
        """Content identity for a playlist item.

        Playlist items carry no GUID, so identity is the item's own fields plus
        the media and locations it points at -- and the playlist it belongs to,
        because JW Library keeps a separate item row per playlist even when the
        same song appears in two of them.
        """
        item_id = row["PlaylistItemId"]
        media = frozenset(
            (media_hash_by_id.get(r["IndependentMediaId"], ""), r["DurationTicks"])
            for r in conn.execute(
                "SELECT * FROM PlaylistItemIndependentMediaMap WHERE PlaylistItemId = ?",
                (item_id,),
            )
        )
        locs = frozenset(
            (
                location_key.get(r["LocationId"], ()),
                r["MajorMultimediaType"],
                r["BaseDurationTicks"],
            )
            for r in conn.execute(
                "SELECT * FROM PlaylistItemLocationMap WHERE PlaylistItemId = ?",
                (item_id,),
            )
        )
        thumb = media_hash_by_path.get(row["ThumbnailFilePath"] or "", "")
        return (
            owning_tag,
            row["Label"],
            row["StartTrimOffsetTicks"],
            row["EndTrimOffsetTicks"],
            row["EndAction"],
            thumb,
            media,
            locs,
        )

    def _owning_tags(self, conn: sqlite3.Connection) -> dict[int, tuple]:
        return {
            r["PlaylistItemId"]: (r["Type"], r["Name"])
            for r in conn.execute(
                "SELECT m.PlaylistItemId, t.Type, t.Name FROM TagMap m"
                " JOIN Tag t ON t.TagId = m.TagId"
                " WHERE m.PlaylistItemId IS NOT NULL"
            )
        }

    def _location_keys(self, conn: sqlite3.Connection) -> dict[int, tuple]:
        return {
            r["LocationId"]: self._location_identity(r)
            for r in conn.execute("SELECT * FROM Location")
        }

    def _merge_playlist_items(
        self,
        src: sqlite3.Connection,
        tags: dict[int, int],
        accuracy: dict[int, int],
        media_ids: dict[int, int],
        media_paths: dict[str, str],
        locations: dict[int, int],
        sr: SourceReport,
    ) -> dict[int, int]:
        tgt_media_by_id = {
            r["IndependentMediaId"]: r["Hash"]
            for r in self.conn.execute("SELECT * FROM IndependentMedia")
        }
        tgt_media_by_path = {
            r["FilePath"]: r["Hash"]
            for r in self.conn.execute("SELECT * FROM IndependentMedia")
        }
        src_media_by_id = {
            r["IndependentMediaId"]: r["Hash"]
            for r in src.execute("SELECT * FROM IndependentMedia")
        }
        src_media_by_path = {
            r["FilePath"]: r["Hash"]
            for r in src.execute("SELECT * FROM IndependentMedia")
        }

        tgt_loc_keys = self._location_keys(self.conn)
        src_loc_keys = self._location_keys(src)
        tgt_owning = self._owning_tags(self.conn)
        src_owning = self._owning_tags(src)

        index: dict[tuple, int] = {}
        for row in self.conn.execute("SELECT * FROM PlaylistItem"):
            key = self._playlist_item_key(
                self.conn,
                row,
                tgt_owning.get(row["PlaylistItemId"]),
                media_hash_by_id=tgt_media_by_id,
                media_hash_by_path=tgt_media_by_path,
                location_key=tgt_loc_keys,
            )
            index.setdefault(key, row["PlaylistItemId"])

        mapping: dict[int, int] = {}
        for row in src.execute("SELECT * FROM PlaylistItem").fetchall():
            src_id = row["PlaylistItemId"]
            key = self._playlist_item_key(
                src,
                row,
                src_owning.get(src_id),
                media_hash_by_id=src_media_by_id,
                media_hash_by_path=src_media_by_path,
                location_key=src_loc_keys,
            )
            if (hit := index.get(key)) is not None:
                mapping[src_id] = hit
                sr.reused["PlaylistItem"] += 1
                continue

            thumb = row["ThumbnailFilePath"]
            if thumb:
                thumb = media_paths.get(thumb, thumb)
                if not self._scalar(
                    "SELECT 1 FROM IndependentMedia WHERE FilePath = ?", thumb
                ):
                    thumb = None

            cur = self.conn.execute(
                "INSERT INTO PlaylistItem(Label, StartTrimOffsetTicks,"
                " EndTrimOffsetTicks, Accuracy, EndAction, ThumbnailFilePath)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["Label"],
                    row["StartTrimOffsetTicks"],
                    row["EndTrimOffsetTicks"],
                    accuracy.get(row["Accuracy"], row["Accuracy"]),
                    row["EndAction"],
                    thumb,
                ),
            )
            mapping[src_id] = cur.lastrowid
            index[key] = cur.lastrowid
            sr.added["PlaylistItem"] += 1

        return mapping

    def _merge_playlist_children(
        self,
        src: sqlite3.Connection,
        items: dict[int, int],
        media_ids: dict[int, int],
        locations: dict[int, int],
        sr: SourceReport,
    ) -> None:
        for row in self._rows(src, "SELECT * FROM PlaylistItemIndependentMediaMap"):
            item = items.get(row["PlaylistItemId"])
            media = media_ids.get(row["IndependentMediaId"])
            if item is None or media is None:
                sr.skipped["PlaylistItemIndependentMediaMap"] += 1
                continue
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO PlaylistItemIndependentMediaMap"
                "(PlaylistItemId, IndependentMediaId, DurationTicks)"
                " VALUES (?, ?, ?)",
                (item, media, row["DurationTicks"]),
            )
            key = "PlaylistItemIndependentMediaMap"
            sr.added[key] += cur.rowcount if cur.rowcount > 0 else 0
            sr.reused[key] += 1 if cur.rowcount == 0 else 0

        for row in self._rows(src, "SELECT * FROM PlaylistItemLocationMap"):
            item = items.get(row["PlaylistItemId"])
            loc = locations.get(row["LocationId"])
            if item is None or loc is None:
                sr.skipped["PlaylistItemLocationMap"] += 1
                continue
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO PlaylistItemLocationMap"
                "(PlaylistItemId, LocationId, MajorMultimediaType, BaseDurationTicks)"
                " VALUES (?, ?, ?, ?)",
                (item, loc, row["MajorMultimediaType"], row["BaseDurationTicks"]),
            )
            key = "PlaylistItemLocationMap"
            sr.added[key] += cur.rowcount if cur.rowcount > 0 else 0
            sr.reused[key] += 1 if cur.rowcount == 0 else 0

        marker_map: dict[int, int] = {}
        for row in self._rows(src, "SELECT * FROM PlaylistItemMarker"):
            item = items.get(row["PlaylistItemId"])
            if item is None:
                sr.skipped["PlaylistItemMarker"] += 1
                continue
            existing = self._scalar(
                "SELECT PlaylistItemMarkerId FROM PlaylistItemMarker"
                " WHERE PlaylistItemId = ? AND StartTimeTicks = ?",
                item,
                row["StartTimeTicks"],
            )
            if existing is not None:
                marker_map[row["PlaylistItemMarkerId"]] = existing
                sr.reused["PlaylistItemMarker"] += 1
                continue
            cur = self.conn.execute(
                "INSERT INTO PlaylistItemMarker(PlaylistItemId, Label, StartTimeTicks,"
                " DurationTicks, EndTransitionDurationTicks) VALUES (?, ?, ?, ?, ?)",
                (
                    item,
                    row["Label"],
                    row["StartTimeTicks"],
                    row["DurationTicks"],
                    row["EndTransitionDurationTicks"],
                ),
            )
            marker_map[row["PlaylistItemMarkerId"]] = cur.lastrowid
            sr.added["PlaylistItemMarker"] += 1

        for row in self._rows(src, "SELECT * FROM PlaylistItemMarkerBibleVerseMap"):
            marker = marker_map.get(row["PlaylistItemMarkerId"])
            if marker is None:
                continue
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO PlaylistItemMarkerBibleVerseMap"
                "(PlaylistItemMarkerId, VerseId) VALUES (?, ?)",
                (marker, row["VerseId"]),
            )
            if cur.rowcount > 0:
                sr.added["PlaylistItemMarkerBibleVerseMap"] += 1

        for row in self._rows(src, "SELECT * FROM PlaylistItemMarkerParagraphMap"):
            marker = marker_map.get(row["PlaylistItemMarkerId"])
            if marker is None:
                continue
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO PlaylistItemMarkerParagraphMap"
                "(PlaylistItemMarkerId, MepsDocumentId, ParagraphIndex,"
                " MarkerIndexWithinParagraph) VALUES (?, ?, ?, ?)",
                (
                    marker,
                    row["MepsDocumentId"],
                    row["ParagraphIndex"],
                    row["MarkerIndexWithinParagraph"],
                ),
            )
            if cur.rowcount > 0:
                sr.added["PlaylistItemMarkerParagraphMap"] += 1

    # -- TagMap --------------------------------------------------------------

    def _merge_tagmaps(
        self,
        src: sqlite3.Connection,
        tags: dict[int, int],
        items: dict[int, int],
        locations: dict[int, int],
        sr: SourceReport,
        notes: dict[int, int] | None = None,
    ) -> None:
        note_by_guid = {
            r["Guid"]: r["NoteId"] for r in self.conn.execute("SELECT * FROM Note")
        }
        src_note_guid = {
            r["NoteId"]: r["Guid"] for r in src.execute("SELECT * FROM Note")
        }

        existing: set[tuple] = set()
        next_position: dict[int, int] = {}
        for r in self.conn.execute("SELECT * FROM TagMap"):
            existing.add(
                _k(r["TagId"], r["PlaylistItemId"], r["LocationId"], r["NoteId"])
            )
            tag = r["TagId"]
            next_position[tag] = max(next_position.get(tag, -1), r["Position"])

        for row in self._rows(src, "SELECT * FROM TagMap ORDER BY TagId, Position"):
            tag = tags.get(row["TagId"])
            if tag is None:
                sr.skipped["TagMap"] += 1
                continue

            item = items.get(row["PlaylistItemId"]) if row["PlaylistItemId"] else None
            loc = locations.get(row["LocationId"]) if row["LocationId"] else None
            note = None
            if row["NoteId"]:
                guid = src_note_guid.get(row["NoteId"])
                note = note_by_guid.get(guid) if guid else None

            if (row["PlaylistItemId"] and item is None) or (
                row["LocationId"] and loc is None
            ) or (row["NoteId"] and note is None):
                sr.skipped["TagMap"] += 1
                continue

            key = _k(tag, item, loc, note)
            if key in existing:
                sr.reused["TagMap"] += 1
                continue

            position = next_position.get(tag, -1) + 1
            self.conn.execute(
                "INSERT INTO TagMap(PlaylistItemId, LocationId, NoteId, TagId, Position)"
                " VALUES (?, ?, ?, ?, ?)",
                (item, loc, note, tag, position),
            )
            next_position[tag] = position
            existing.add(key)
            sr.added["TagMap"] += 1

    # -- finishing -----------------------------------------------------------

    def finalize(self, report: MergeReport) -> None:
        """Refresh the LastModified stamp and verify referential integrity."""
        self.conn.execute(
            "UPDATE LastModified SET LastModified ="
            " strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
        )
        if self.options.check_integrity:
            for row in self.conn.execute("PRAGMA foreign_key_check"):
                report.integrity_errors.append(
                    f"{row[0]}: rowid {row[1]} -> {row[2]} (fk #{row[3]})"
                )
        self.conn.commit()


def merge_backups(
    base: Backup,
    sources: list[Backup],
    workdir: Path,
    options: MergeOptions | None = None,
) -> tuple[Path, MediaPlan, MergeReport]:
    """Merge ``sources`` into a copy of ``base``.

    Returns the merged database path, the media files the output archive needs,
    and a report describing every decision.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    db_path = workdir / base.manifest.database_name
    shutil.copy2(base.db_path, db_path)

    media = MediaPlan()
    for entry in base.media_files():
        media.add(entry.relative_to(base.workdir).as_posix(), entry)

    report = MergeReport(
        base=base.path.name,
        base_device=base.manifest.device_name,
        schema_version=base.manifest.schema_version,
    )

    conn = sqlite3.connect(db_path)
    try:
        merger = Merger(conn, media, options)
        report.totals_before = merger.counts()
        for source in sources:
            if source.manifest.schema_version != base.manifest.schema_version:
                raise MergeError(
                    f"{source.path.name} uses schema version "
                    f"{source.manifest.schema_version} but the base uses "
                    f"{base.manifest.schema_version}; open both backups in the "
                    "same JW Library version and export them again"
                )
            merger.merge_backup(source, report)
        merger.finalize(report)
        report.totals_after = merger.counts()
    finally:
        conn.close()

    return db_path, media, report


__all__ = [
    "MAX_BOOKMARK_SLOT",
    "MediaPlan",
    "MergeError",
    "MergeOptions",
    "Merger",
    "merge_backups",
]
