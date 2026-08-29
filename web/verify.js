// Prove that a merged backup lost nothing.
//
// The merge reports what it did; this checks the result independently, by
// walking every note, highlight, bookmark, tag, study answer, media file and
// playlist item in each source and asserting it is findable in the merged
// database under the identity the merge uses.
//
// Mirrors src/jwsync/verify.py.

import {
  all,
  key,
  locationIdentity,
  mediaContext,
  owningTags,
  playlistItemKey,
} from "./merge.js";

// key() is imported rather than repeated, so the verifier and the merge
// cannot drift apart and disagree about what identifies a row.

function locationById(db) {
  const out = new Map();
  for (const row of all(db, "SELECT * FROM Location")) {
    out.set(row.LocationId, locationIdentity(row));
  }
  return out;
}

/**
 * @param merged  sql.js Database of the merged library
 * @param sources array of { label, db } for each backup that went into it
 * @param present set of archive member names actually in the merged file
 */
export function verify(merged, sources, present) {
  const result = { checked: {}, missing: [], mediaMissingFiles: [] };
  const note = (table) => {
    result.checked[table] = (result.checked[table] || 0) + 1;
  };
  const miss = (table, description) => result.missing.push({ table, description });

  const noteGuids = new Set(all(merged, "SELECT Guid FROM Note").map((r) => r.Guid));
  const markGuids = new Set(
    all(merged, "SELECT UserMarkGuid FROM UserMark").map((r) => r.UserMarkGuid)
  );
  const tags = new Set(
    all(merged, "SELECT * FROM Tag").map((r) => key(r.Type, r.Name))
  );
  const locations = new Set(locationById(merged).values());
  const mediaHashes = new Set(
    all(merged, "SELECT Hash FROM IndependentMedia").map((r) => r.Hash)
  );

  const mergedLoc = locationById(merged);
  const bookmarks = new Set(
    all(merged, "SELECT * FROM Bookmark").map((r) =>
      key(
        mergedLoc.get(r.PublicationLocationId),
        mergedLoc.get(r.LocationId),
        r.BlockType,
        r.BlockIdentifier
      )
    )
  );
  const inputFields = new Set(
    all(merged, "SELECT * FROM InputField").map((r) =>
      key(mergedLoc.get(r.LocationId), r.TextTag)
    )
  );

  const mergedCtx = mediaContext(merged);
  const mergedOwning = owningTags(merged);
  const playlistItems = new Set(
    all(merged, "SELECT * FROM PlaylistItem").map((r) =>
      playlistItemKey(merged, r, mergedOwning.get(r.PlaylistItemId), mergedCtx)
    )
  );

  if (present) {
    for (const row of all(merged, "SELECT FilePath FROM IndependentMedia")) {
      if (!present.has(row.FilePath)) result.mediaMissingFiles.push(row.FilePath);
    }
  }

  for (const { label, db } of sources) {
    for (const row of all(db, "SELECT * FROM Note")) {
      note("Note");
      if (!noteGuids.has(row.Guid)) {
        miss("Note", `${label}: a note (${(row.Title || "").slice(0, 40)})`);
      }
    }

    for (const row of all(db, "SELECT UserMarkGuid FROM UserMark")) {
      note("UserMark");
      if (!markGuids.has(row.UserMarkGuid)) {
        miss("UserMark", `${label}: highlight ${row.UserMarkGuid}`);
      }
    }

    for (const row of all(db, "SELECT * FROM Tag")) {
      note("Tag");
      if (!tags.has(key(row.Type, row.Name))) {
        miss("Tag", `${label}: tag "${row.Name}"`);
      }
    }

    const sourceLoc = locationById(db);
    for (const row of all(db, "SELECT * FROM Location")) {
      note("Location");
      if (!locations.has(locationIdentity(row))) {
        miss("Location", `${label}: a location in ${row.KeySymbol || "?"}`);
      }
    }

    for (const row of all(db, "SELECT * FROM IndependentMedia")) {
      note("IndependentMedia");
      if (!mediaHashes.has(row.Hash)) {
        miss("IndependentMedia", `${label}: media "${row.OriginalFilename}"`);
      }
    }

    for (const row of all(db, "SELECT * FROM Bookmark")) {
      note("Bookmark");
      const k = key(
        sourceLoc.get(row.PublicationLocationId),
        sourceLoc.get(row.LocationId),
        row.BlockType,
        row.BlockIdentifier
      );
      // Both sides key on location identity rather than the row ids the merge
      // renumbers, so these keys compare directly. A prefix match would let a
      // genuinely missing bookmark pass.
      if (!bookmarks.has(k)) {
        miss("Bookmark", `${label}: bookmark "${row.Title}"`);
      }
    }

    for (const row of all(db, "SELECT * FROM InputField")) {
      note("InputField");
      const k = key(sourceLoc.get(row.LocationId), row.TextTag);
      if (!inputFields.has(k)) {
        miss("InputField", `${label}: study answer "${row.TextTag}"`);
      }
    }

    const sourceCtx = mediaContext(db);
    const sourceOwning = owningTags(db);
    for (const row of all(db, "SELECT * FROM PlaylistItem")) {
      note("PlaylistItem");
      const k = playlistItemKey(db, row, sourceOwning.get(row.PlaylistItemId), sourceCtx);
      if (!playlistItems.has(k)) {
        miss("PlaylistItem", `${label}: playlist item "${row.Label}"`);
      }
    }
  }

  result.ok = result.missing.length === 0 && result.mediaMissingFiles.length === 0;
  return result;
}
