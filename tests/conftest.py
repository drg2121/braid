"""Fixture factory: build small but structurally real ``.jwlibrary`` archives.

The archives here are synthesised from the published schema, not copied from
anybody's library, so the test suite carries no personal study data.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import uuid
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from braid.archive import jw_hex  # noqa: E402

SCHEMA_PATH = Path(__file__).parent / "fixtures" / "schema_v16.sql"
TABLES_MARKER = "-- >>> TABLES AND INDEXES"
TRIGGERS_MARKER = "-- >>> TRIGGERS"


def _schema_halves() -> tuple[str, str]:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    head, _, tail = text.partition(TRIGGERS_MARKER)
    return head.partition(TABLES_MARKER)[2], tail


class BackupBuilder:
    """Assembles a ``.jwlibrary`` archive one row at a time."""

    def __init__(self, path: Path, device: str, last_modified: str) -> None:
        self.path = Path(path)
        self.device = device
        self.last_modified = last_modified
        self.workdir = self.path.parent / f".build-{self.path.stem}"
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.workdir / "userData.db"
        self.blobs: dict[str, bytes] = {}

        tables, triggers = _schema_halves()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(tables)
        # Seed the singleton row while INSERT is still permitted.
        self.conn.execute(
            "INSERT INTO LastModified(LastModified) VALUES (?)", (last_modified,)
        )
        self.conn.executescript(triggers)
        for identifier in ("v14", "v15", "v16"):
            self.conn.execute(
                "INSERT INTO grdb_migrations(identifier) VALUES (?)", (identifier,)
            )
        for description in ("Accurate", "Inaccurate"):
            self.conn.execute(
                "INSERT INTO PlaylistItemAccuracy(Description) VALUES (?)",
                (description,),
            )
        self.conn.commit()

    # -- row helpers ---------------------------------------------------

    def location(self, **kw) -> int:
        row = {
            "BookNumber": None,
            "ChapterNumber": None,
            "DocumentId": None,
            "Track": None,
            "IssueTagNumber": 0,
            "KeySymbol": None,
            "MepsLanguage": 294,
            "Type": 0,
            "Title": None,
            "Specialty": None,
            "Edition": None,
        }
        row.update(kw)
        cols = ", ".join(row)
        holes = ", ".join("?" for _ in row)
        cur = self.conn.execute(
            f"INSERT INTO Location({cols}) VALUES ({holes})", tuple(row.values())
        )
        return cur.lastrowid

    def tag(self, name: str, type_: int = 1) -> int:
        cur = self.conn.execute(
            "INSERT INTO Tag(Type, Name) VALUES (?, ?)", (type_, name)
        )
        return cur.lastrowid

    def usermark(
        self, location_id: int, guid: str, color: int = 1, version: int = 1
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO UserMark(ColorIndex, LocationId, StyleIndex, UserMarkGuid,"
            " Version) VALUES (?, ?, 0, ?, ?)",
            (color, location_id, guid, version),
        )
        return cur.lastrowid

    def block_range(
        self, usermark_id: int, identifier: int = 1, start: int = 0, end: int = 5
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO BlockRange(BlockType, Identifier, StartToken, EndToken,"
            " UserMarkId) VALUES (1, ?, ?, ?, ?)",
            (identifier, start, end, usermark_id),
        )
        return cur.lastrowid

    def note(
        self,
        guid: str,
        *,
        title: str = "",
        content: str = "",
        location_id: int | None = None,
        usermark_id: int | None = None,
        last_modified: str = "2026-01-01T00:00:00Z",
        created: str = "2026-01-01T00:00:00Z",
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO Note(Guid, UserMarkId, LocationId, Title, Content,"
            " LastModified, Created, BlockType) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (guid, usermark_id, location_id, title, content, last_modified, created),
        )
        return cur.lastrowid

    def bookmark(
        self,
        publication_location_id: int,
        location_id: int,
        slot: int,
        title: str,
        block_identifier: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO Bookmark(LocationId, PublicationLocationId, Slot, Title,"
            " Snippet, BlockType, BlockIdentifier) VALUES (?, ?, ?, ?, NULL, ?, ?)",
            (
                location_id,
                publication_location_id,
                slot,
                title,
                0 if block_identifier is None else 1,
                block_identifier,
            ),
        )
        return cur.lastrowid

    def input_field(self, location_id: int, tag: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO InputField(LocationId, TextTag, Value) VALUES (?, ?, ?)",
            (location_id, tag, value),
        )

    def media(self, payload: bytes, filename: str, mime: str = "audio/mpeg") -> str:
        import hashlib

        file_path = f"{uuid.uuid4()}{Path(filename).suffix}"
        self.conn.execute(
            "INSERT INTO IndependentMedia(OriginalFilename, FilePath, MimeType, Hash)"
            " VALUES (?, ?, ?, ?)",
            (filename, file_path, mime, jw_hex(hashlib.sha256(payload).digest())),
        )
        self.blobs[file_path] = payload
        return file_path

    def media_named(self, payload: bytes, file_path: str, mime: str = "image/png") -> str:
        """Media stored under an exact, non-random FilePath (collision testing)."""
        import hashlib

        self.conn.execute(
            "INSERT INTO IndependentMedia(OriginalFilename, FilePath, MimeType, Hash)"
            " VALUES (?, ?, ?, ?)",
            (file_path, file_path, mime, jw_hex(hashlib.sha256(payload).digest())),
        )
        self.blobs[file_path] = payload
        return file_path

    def playlist_item(
        self, label: str, *, thumbnail: str | None = None, end_action: int = 0
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO PlaylistItem(Label, StartTrimOffsetTicks, EndTrimOffsetTicks,"
            " Accuracy, EndAction, ThumbnailFilePath) VALUES (?, NULL, NULL, 1, ?, ?)",
            (label, end_action, thumbnail),
        )
        return cur.lastrowid

    def playlist_media(
        self, item_id: int, file_path: str, duration: int = 1000
    ) -> None:
        media_id = self.conn.execute(
            "SELECT IndependentMediaId FROM IndependentMedia WHERE FilePath = ?",
            (file_path,),
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO PlaylistItemIndependentMediaMap(PlaylistItemId,"
            " IndependentMediaId, DurationTicks) VALUES (?, ?, ?)",
            (item_id, media_id, duration),
        )

    def tag_map(
        self,
        tag_id: int,
        position: int,
        *,
        note_id: int | None = None,
        location_id: int | None = None,
        playlist_item_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO TagMap(PlaylistItemId, LocationId, NoteId, TagId, Position)"
            " VALUES (?, ?, ?, ?, ?)",
            (playlist_item_id, location_id, note_id, tag_id, position),
        )
        return cur.lastrowid

    # -- output ---------------------------------------------------------

    def build(self) -> Path:
        self.conn.commit()
        self.conn.close()
        manifest = {
            "name": self.path.name,
            "creationDate": "2026-08-29T12:00:00+0000",
            "version": 1,
            "type": 0,
            "userDataBackup": {
                "schemaVersion": 16,
                "databaseName": "userData.db",
                "deviceName": self.device,
                "lastModifiedDate": self.last_modified,
                "hash": "0" * 63,
            },
        }
        with zipfile.ZipFile(self.path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.write(self.db_path, "userData.db")
            for name, payload in self.blobs.items():
                zf.writestr(name, payload)
        return self.path


@pytest.fixture
def builder(tmp_path):
    def make(name: str, device: str, last_modified: str) -> BackupBuilder:
        return BackupBuilder(tmp_path / name, device, last_modified)

    return make
