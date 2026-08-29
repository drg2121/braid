"""Prove that a merged backup lost nothing.

The merge engine reports what it did; this checks the result independently.
For every source backup it walks the user's own data -- notes, highlights,
bookmarks, tags, study answers, media and playlists -- and asserts that each
item is findable in the merged database under the identity the merge uses.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .archive import Backup
from .merge import Merger, _k


@dataclass
class Missing:
    """One item from a source that could not be found in the merged file."""

    table: str
    identity: str
    description: str


@dataclass
class VerifyResult:
    merged: str
    checked: dict[str, int] = field(default_factory=dict)
    missing: list[Missing] = field(default_factory=list)
    media_missing_files: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.media_missing_files

    def to_dict(self) -> dict:
        return {
            "merged": self.merged,
            "sources": self.sources,
            "ok": self.ok,
            "checked": self.checked,
            "missing": [
                {"table": m.table, "identity": m.identity, "description": m.description}
                for m in self.missing
            ],
            "mediaMissingFiles": self.media_missing_files,
        }

    def to_text(self) -> str:
        lines = [f"merged  : {self.merged}"]
        for src in self.sources:
            lines.append(f"source  : {src}")
        lines.append("")
        lines.append("items checked and found in the merged file")
        for table, n in sorted(self.checked.items()):
            lines.append(f"  {table:<34}{n:>7}")

        if self.missing:
            lines.append("")
            lines.append(f"MISSING ({len(self.missing)})")
            for m in self.missing[:50]:
                lines.append(f"  {m.table}: {m.description}")
            if len(self.missing) > 50:
                lines.append(f"  ... and {len(self.missing) - 50} more")

        if self.media_missing_files:
            lines.append("")
            lines.append("MEDIA FILES REFERENCED BUT ABSENT FROM THE ARCHIVE")
            for name in self.media_missing_files[:50]:
                lines.append(f"  {name}")

        lines.append("")
        lines.append(
            "PASS -- every item from every source is present"
            if self.ok
            else "FAIL -- see above"
        )
        return "\n".join(lines)


def _playlist_context(conn: sqlite3.Connection) -> dict:
    return {
        "media_hash_by_id": {
            r["IndependentMediaId"]: r["Hash"]
            for r in conn.execute("SELECT * FROM IndependentMedia")
        },
        "media_hash_by_path": {
            r["FilePath"]: r["Hash"]
            for r in conn.execute("SELECT * FROM IndependentMedia")
        },
        "location_key": {
            r["LocationId"]: Merger._location_identity(r)
            for r in conn.execute("SELECT * FROM Location")
        },
    }


def _owning_tags(conn: sqlite3.Connection) -> dict[int, tuple]:
    return {
        r["PlaylistItemId"]: (r["Type"], r["Name"])
        for r in conn.execute(
            "SELECT m.PlaylistItemId, t.Type, t.Name FROM TagMap m"
            " JOIN Tag t ON t.TagId = m.TagId WHERE m.PlaylistItemId IS NOT NULL"
        )
    }


def verify(merged_path: Path, source_paths: list[Path]) -> VerifyResult:
    """Check that every user-owned item in each source survives in the merge."""
    result = VerifyResult(merged=str(merged_path))
    merged = Backup.open(merged_path)
    try:
        out = merged.connect()
        out.row_factory = sqlite3.Row

        # Index the merged file once, by the same identities the merge uses.
        note_guids = {r["Guid"] for r in out.execute("SELECT Guid FROM Note")}
        mark_guids = {
            r["UserMarkGuid"] for r in out.execute("SELECT UserMarkGuid FROM UserMark")
        }
        tags = {(r["Type"], r["Name"]) for r in out.execute("SELECT * FROM Tag")}
        locations = {
            Merger._location_identity(r): r["LocationId"]
            for r in out.execute("SELECT * FROM Location")
        }
        media_hashes = {
            r["Hash"] for r in out.execute("SELECT Hash FROM IndependentMedia")
        }
        out_ctx = _playlist_context(out)
        out_owning = _owning_tags(out)
        playlist_items = {
            Merger._playlist_item_key(
                out, r, out_owning.get(r["PlaylistItemId"]), **out_ctx
            )
            for r in out.execute("SELECT * FROM PlaylistItem")
        }
        bookmarks = set()
        for r in out.execute("SELECT * FROM Bookmark"):
            pub = out.execute(
                "SELECT * FROM Location WHERE LocationId = ?",
                (r["PublicationLocationId"],),
            ).fetchone()
            loc = out.execute(
                "SELECT * FROM Location WHERE LocationId = ?", (r["LocationId"],)
            ).fetchone()
            bookmarks.add(
                _k(
                    Merger._location_identity(pub) if pub else None,
                    Merger._location_identity(loc) if loc else None,
                    r["BlockType"],
                    r["BlockIdentifier"],
                )
            )
        input_fields = set()
        for r in out.execute("SELECT * FROM InputField"):
            loc = out.execute(
                "SELECT * FROM Location WHERE LocationId = ?", (r["LocationId"],)
            ).fetchone()
            input_fields.add(
                _k(Merger._location_identity(loc) if loc else None, r["TextTag"])
            )

        # Media files must physically exist in the merged archive.
        present = {
            p.relative_to(merged.workdir).as_posix() for p in merged.media_files()
        }
        for r in out.execute("SELECT FilePath FROM IndependentMedia"):
            if r["FilePath"] not in present:
                result.media_missing_files.append(r["FilePath"])

        for path in source_paths:
            result.sources.append(str(path))
            with Backup.open(path) as source:
                src = source.connect()
                src.row_factory = sqlite3.Row
                label = path.name

                for r in src.execute("SELECT * FROM Note"):
                    result.checked["Note"] = result.checked.get("Note", 0) + 1
                    if r["Guid"] not in note_guids:
                        title = (r["Title"] or "")[:40]
                        result.missing.append(
                            Missing(
                                "Note",
                                r["Guid"],
                                f"{label}: note {r['Guid']} ({title!r})",
                            )
                        )

                for r in src.execute("SELECT * FROM UserMark"):
                    result.checked["UserMark"] = result.checked.get("UserMark", 0) + 1
                    if r["UserMarkGuid"] not in mark_guids:
                        result.missing.append(
                            Missing(
                                "UserMark",
                                r["UserMarkGuid"],
                                f"{label}: highlight {r['UserMarkGuid']}",
                            )
                        )

                for r in src.execute("SELECT * FROM Tag"):
                    result.checked["Tag"] = result.checked.get("Tag", 0) + 1
                    if (r["Type"], r["Name"]) not in tags:
                        result.missing.append(
                            Missing("Tag", r["Name"], f"{label}: tag {r['Name']!r}")
                        )

                for r in src.execute("SELECT * FROM Location"):
                    result.checked["Location"] = result.checked.get("Location", 0) + 1
                    if Merger._location_identity(r) not in locations:
                        result.missing.append(
                            Missing(
                                "Location",
                                str(r["LocationId"]),
                                f"{label}: location {r['KeySymbol']!r}"
                                f" doc={r['DocumentId']} book={r['BookNumber']}",
                            )
                        )

                for r in src.execute("SELECT * FROM IndependentMedia"):
                    result.checked["IndependentMedia"] = (
                        result.checked.get("IndependentMedia", 0) + 1
                    )
                    if r["Hash"] not in media_hashes:
                        result.missing.append(
                            Missing(
                                "IndependentMedia",
                                r["Hash"],
                                f"{label}: media {r['OriginalFilename']!r}",
                            )
                        )

                for r in src.execute("SELECT * FROM Bookmark"):
                    result.checked["Bookmark"] = result.checked.get("Bookmark", 0) + 1
                    pub = src.execute(
                        "SELECT * FROM Location WHERE LocationId = ?",
                        (r["PublicationLocationId"],),
                    ).fetchone()
                    loc = src.execute(
                        "SELECT * FROM Location WHERE LocationId = ?",
                        (r["LocationId"],),
                    ).fetchone()
                    key = _k(
                        Merger._location_identity(pub) if pub else None,
                        Merger._location_identity(loc) if loc else None,
                        r["BlockType"],
                        r["BlockIdentifier"],
                    )
                    if key not in bookmarks:
                        result.missing.append(
                            Missing(
                                "Bookmark",
                                str(r["BookmarkId"]),
                                f"{label}: bookmark {r['Title']!r}",
                            )
                        )

                for r in src.execute("SELECT * FROM InputField"):
                    result.checked["InputField"] = (
                        result.checked.get("InputField", 0) + 1
                    )
                    loc = src.execute(
                        "SELECT * FROM Location WHERE LocationId = ?",
                        (r["LocationId"],),
                    ).fetchone()
                    key = _k(
                        Merger._location_identity(loc) if loc else None, r["TextTag"]
                    )
                    if key not in input_fields:
                        result.missing.append(
                            Missing(
                                "InputField",
                                r["TextTag"],
                                f"{label}: study answer {r['TextTag']!r}",
                            )
                        )

                src_ctx = _playlist_context(src)
                src_owning = _owning_tags(src)
                for r in src.execute("SELECT * FROM PlaylistItem"):
                    result.checked["PlaylistItem"] = (
                        result.checked.get("PlaylistItem", 0) + 1
                    )
                    key = Merger._playlist_item_key(
                        src, r, src_owning.get(r["PlaylistItemId"]), **src_ctx
                    )
                    if key not in playlist_items:
                        result.missing.append(
                            Missing(
                                "PlaylistItem",
                                str(r["PlaylistItemId"]),
                                f"{label}: playlist item {r['Label']!r}",
                            )
                        )

                src.close()

        out.close()
    finally:
        merged.close()

    return result


__all__ = ["Missing", "VerifyResult", "verify"]
