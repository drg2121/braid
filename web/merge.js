// The merge engine, in the browser.
//
// This is the same algorithm as the Python implementation in src/jwsync/merge.py
// and must stay in step with it: every table is keyed on the identity JW
// Library itself uses, so the same note or highlight seen from two devices
// collapses into one row. The merge only ever adds, and merging the same
// source twice adds nothing the second time.

export const MAX_BOOKMARK_SLOT = 9;

export const COUNTED_TABLES = [
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
];

// Separates key components, and stands in for NULL. Neither can occur inside a
// JW Library value, so distinct rows cannot collide on a shared key.
const UNIT = "\u001f";
const NULL_SENTINEL = "\u001eNULL\u001e";

export class MergeError extends Error {}

/** A key that treats NULL as a value of its own. */
export function key(...values) {
  return values
    .map((v) => (v === null || v === undefined ? NULL_SENTINEL : String(v)))
    .join(UNIT);
}

// -- small helpers over sql.js --------------------------------------------

function all(db, sql, params = []) {
  const stmt = db.prepare(sql);
  try {
    stmt.bind(params);
    const rows = [];
    while (stmt.step()) rows.push(stmt.getAsObject());
    return rows;
  } finally {
    stmt.free();
  }
}

function scalar(db, sql, params = []) {
  const rows = all(db, sql, params);
  if (!rows.length) return null;
  return Object.values(rows[0])[0];
}

function run(db, sql, params = []) {
  db.run(sql, params);
  return scalar(db, "SELECT last_insert_rowid()");
}

function count(db, table) {
  try {
    return scalar(db, `SELECT COUNT(*) FROM ${table}`) ?? 0;
  } catch {
    return 0;
  }
}

export function countsOf(db) {
  const out = {};
  for (const table of COUNTED_TABLES) out[table] = count(db, table);
  return out;
}

// -- identity keys ---------------------------------------------------------

export function locationIdentity(row) {
  return key(
    row.BookNumber,
    row.ChapterNumber,
    row.DocumentId,
    row.Track,
    row.IssueTagNumber,
    row.KeySymbol,
    row.MepsLanguage,
    row.Type,
    row.Specialty,
    row.Edition
  );
}

/** The table's UNIQUE constraint, or null where a NULL makes SQLite skip it. */
function locationUniqueKey(row) {
  const parts = [
    row.BookNumber,
    row.ChapterNumber,
    row.KeySymbol,
    row.MepsLanguage,
    row.Type,
  ];
  return parts.some((p) => p === null || p === undefined) ? null : key(...parts);
}

/** The IX_Location_Media unique index, under the same NULL rule. */
function locationMediaKey(row) {
  const parts = [
    row.KeySymbol,
    row.IssueTagNumber,
    row.MepsLanguage,
    row.DocumentId,
    row.Track,
    row.Type,
  ];
  if (parts.some((p) => p === null || p === undefined)) return null;
  return key(...parts, row.Specialty || "", row.Edition || "");
}

function owningTags(db) {
  const out = new Map();
  for (const row of all(
    db,
    "SELECT m.PlaylistItemId, t.Type, t.Name FROM TagMap m" +
      " JOIN Tag t ON t.TagId = m.TagId WHERE m.PlaylistItemId IS NOT NULL"
  )) {
    out.set(row.PlaylistItemId, key(row.Type, row.Name));
  }
  return out;
}

function locationKeys(db) {
  const out = new Map();
  for (const row of all(db, "SELECT * FROM Location")) {
    out.set(row.LocationId, locationIdentity(row));
  }
  return out;
}

/**
 * Content identity for a playlist item.
 *
 * Playlist items carry no GUID, so identity is the item's own fields plus the
 * media and locations it points at -- and the playlist it belongs to, because
 * JW Library keeps a separate item row per playlist even when the same song
 * appears in two of them.
 */
export function playlistItemKey(db, row, owningTag, ctx) {
  const media = all(
    db,
    "SELECT * FROM PlaylistItemIndependentMediaMap WHERE PlaylistItemId = ?",
    [row.PlaylistItemId]
  )
    .map((r) => key(ctx.mediaHashById.get(r.IndependentMediaId) || "", r.DurationTicks))
    .sort()
    .join(UNIT);

  const locations = all(
    db,
    "SELECT * FROM PlaylistItemLocationMap WHERE PlaylistItemId = ?",
    [row.PlaylistItemId]
  )
    .map((r) =>
      key(
        ctx.locationKey.get(r.LocationId) || "",
        r.MajorMultimediaType,
        r.BaseDurationTicks
      )
    )
    .sort()
    .join(UNIT);

  const thumb = ctx.mediaHashByPath.get(row.ThumbnailFilePath || "") || "";
  return key(
    owningTag || "",
    row.Label,
    row.StartTrimOffsetTicks,
    row.EndTrimOffsetTicks,
    row.EndAction,
    thumb,
    media,
    locations
  );
}

export function mediaContext(db) {
  const mediaHashById = new Map();
  const mediaHashByPath = new Map();
  for (const row of all(db, "SELECT * FROM IndependentMedia")) {
    mediaHashById.set(row.IndependentMediaId, row.Hash);
    mediaHashByPath.set(row.FilePath, row.Hash);
  }
  return { mediaHashById, mediaHashByPath, locationKey: locationKeys(db) };
}

export { owningTags };

// -- report ----------------------------------------------------------------

class SourceReport {
  constructor(name, device, lastModified) {
    this.name = name;
    this.device = device;
    this.lastModified = lastModified;
    this.added = {};
    this.reused = {};
    this.updated = {};
    this.skipped = {};
    this.conflicts = [];
    this.mediaAdded = 0;
    this.mediaReused = 0;
    this.mediaRenamed = [];
  }

  bump(bucket, table, n = 1) {
    this[bucket][table] = (this[bucket][table] || 0) + n;
  }

  conflict(table, detail, resolution) {
    this.conflicts.push({ table, detail, resolution });
  }
}

// -- the engine ------------------------------------------------------------

/**
 * Merge `sources` into `db`, the base database opened for writing.
 *
 * `Database` is the sql.js constructor. `mediaPlan` maps an output archive
 * member name to where its bytes come from. `options.inputFields` is "keep"
 * or "overwrite".
 */
export async function mergeInto(db, Database, base, sources, mediaPlan, options = {}) {
  const inputFields = options.inputFields || "keep";
  const onProgress = options.onProgress || (() => {});

  const report = {
    base: base.file.name,
    baseDevice: base.deviceName,
    sources: [],
    totalsBefore: countsOf(db),
    totalsAfter: {},
    integrityErrors: [],
  };

  for (const source of sources) {
    if (source.schemaVersion !== base.schemaVersion) {
      throw new MergeError(
        `${source.file.name} uses schema version ${source.schemaVersion} but ` +
          `${base.file.name} uses ${base.schemaVersion}. Update JW Library on ` +
          `both devices and make the backups again.`
      );
    }
  }

  let done = 0;
  for (const source of sources) {
    onProgress(`Merging ${source.file.name}`, done / sources.length);
    const sourceDb = new Database(await source.databaseBytes());
    const sr = new SourceReport(
      source.file.name,
      source.deviceName,
      source.lastModified
    );
    report.sources.push(sr);
    try {
      mergeMigrations(db, sourceDb);
      const accuracy = mergeAccuracy(db, sourceDb, sr);
      const locations = mergeLocations(db, sourceDb, sr);
      const { mediaIds, mediaPaths } = mergeMedia(db, sourceDb, source, mediaPlan, sr);
      const marks = mergeUserMarks(db, sourceDb, locations, sr);
      mergeNotes(db, sourceDb, marks, locations, sr);
      mergeBookmarks(db, sourceDb, locations, sr);
      mergeInputFields(db, sourceDb, locations, inputFields, sr);
      const tags = mergeTags(db, sourceDb, sr);
      const items = mergePlaylistItems(db, sourceDb, accuracy, mediaPaths, sr);
      mergePlaylistChildren(db, sourceDb, items, mediaIds, locations, sr);
      mergeTagMaps(db, sourceDb, tags, items, locations, sr);
    } finally {
      sourceDb.close();
    }
    done += 1;
  }

  db.run("UPDATE LastModified SET LastModified = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')");
  for (const row of all(db, "PRAGMA foreign_key_check")) {
    report.integrityErrors.push(Object.values(row).join(" "));
  }
  report.totalsAfter = countsOf(db);
  return report;
}

function mergeMigrations(db, src) {
  for (const row of all(src, "SELECT identifier FROM grdb_migrations")) {
    db.run("INSERT OR IGNORE INTO grdb_migrations(identifier) VALUES (?)", [
      row.identifier,
    ]);
  }
}

function mergeAccuracy(db, src, sr) {
  const index = new Map(
    all(db, "SELECT * FROM PlaylistItemAccuracy").map((r) => [
      r.Description,
      r.PlaylistItemAccuracyId,
    ])
  );
  const map = new Map();
  for (const row of all(src, "SELECT * FROM PlaylistItemAccuracy")) {
    if (index.has(row.Description)) {
      map.set(row.PlaylistItemAccuracyId, index.get(row.Description));
      sr.bump("reused", "PlaylistItemAccuracy");
      continue;
    }
    const id = run(db, "INSERT INTO PlaylistItemAccuracy(Description) VALUES (?)", [
      row.Description,
    ]);
    index.set(row.Description, id);
    map.set(row.PlaylistItemAccuracyId, id);
    sr.bump("added", "PlaylistItemAccuracy");
  }
  return map;
}

const LOCATION_COLUMNS = [
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
];

function mergeLocations(db, src, sr) {
  const byIdentity = new Map();
  const byUnique = new Map();
  const byMedia = new Map();
  for (const row of all(db, "SELECT * FROM Location")) {
    byIdentity.set(locationIdentity(row), row.LocationId);
    const k1 = locationUniqueKey(row);
    if (k1 !== null && !byUnique.has(k1)) byUnique.set(k1, row.LocationId);
    const k2 = locationMediaKey(row);
    if (k2 !== null && !byMedia.has(k2)) byMedia.set(k2, row.LocationId);
  }

  const map = new Map();
  const holes = LOCATION_COLUMNS.map(() => "?").join(", ");
  for (const row of all(src, "SELECT * FROM Location")) {
    const identity = locationIdentity(row);
    if (byIdentity.has(identity)) {
      map.set(row.LocationId, byIdentity.get(identity));
      sr.bump("reused", "Location");
      continue;
    }

    const k1 = locationUniqueKey(row);
    const k2 = locationMediaKey(row);
    const clash =
      (k1 !== null ? byUnique.get(k1) : undefined) ??
      (k2 !== null ? byMedia.get(k2) : undefined);
    if (clash !== undefined) {
      map.set(row.LocationId, clash);
      sr.bump("reused", "Location");
      sr.conflict(
        "Location",
        `source LocationId ${row.LocationId} collides with target ` +
          `LocationId ${clash} on a UNIQUE key`,
        "mapped onto the existing location"
      );
      continue;
    }

    const id = run(
      db,
      `INSERT INTO Location(${LOCATION_COLUMNS.join(", ")}) VALUES (${holes})`,
      LOCATION_COLUMNS.map((c) => (row[c] === undefined ? null : row[c]))
    );
    map.set(row.LocationId, id);
    byIdentity.set(identity, id);
    if (k1 !== null && !byUnique.has(k1)) byUnique.set(k1, id);
    if (k2 !== null && !byMedia.has(k2)) byMedia.set(k2, id);
    sr.bump("added", "Location");
  }
  return map;
}

function mergeMedia(db, src, source, mediaPlan, sr) {
  const byHash = new Map();
  const takenPaths = new Set();
  for (const row of all(db, "SELECT * FROM IndependentMedia")) {
    if (!byHash.has(row.Hash)) byHash.set(row.Hash, row);
    takenPaths.add(row.FilePath);
  }

  const mediaIds = new Map();
  const mediaPaths = new Map();

  for (const row of all(src, "SELECT * FROM IndependentMedia")) {
    const existing = byHash.get(row.Hash);
    if (existing) {
      mediaIds.set(row.IndependentMediaId, existing.IndependentMediaId);
      mediaPaths.set(row.FilePath, existing.FilePath);
      sr.mediaReused += 1;
      sr.bump("reused", "IndependentMedia");
      continue;
    }

    let member = row.FilePath;
    if (takenPaths.has(member) || mediaPlan.has(member)) {
      const dot = member.lastIndexOf(".");
      const suffix = dot > 0 ? member.slice(dot) : "";
      member = `${crypto.randomUUID()}${suffix}`;
      sr.mediaRenamed.push({ from: row.FilePath, to: member });
    }

    const id = run(
      db,
      "INSERT INTO IndependentMedia(OriginalFilename, FilePath, MimeType, Hash)" +
        " VALUES (?, ?, ?, ?)",
      [row.OriginalFilename, member, row.MimeType, row.Hash]
    );
    mediaIds.set(row.IndependentMediaId, id);
    mediaPaths.set(row.FilePath, member);
    takenPaths.add(member);
    byHash.set(row.Hash, { ...row, IndependentMediaId: id, FilePath: member });

    const entry = source.entry(row.FilePath);
    if (entry) {
      mediaPlan.set(member, { backup: source, entry });
      sr.mediaAdded += 1;
    } else {
      sr.bump("skipped", "IndependentMediaFile");
      sr.conflict(
        "IndependentMedia",
        `${row.FilePath} is referenced by the database but is not in the archive`,
        "row kept, file missing"
      );
    }
  }

  return { mediaIds, mediaPaths };
}

function mergeUserMarks(db, src, locations, sr) {
  const index = new Map(all(db, "SELECT * FROM UserMark").map((r) => [r.UserMarkGuid, r]));
  const map = new Map();

  for (const row of all(src, "SELECT * FROM UserMark")) {
    const loc = locations.get(row.LocationId);
    if (loc === undefined) {
      sr.bump("skipped", "UserMark");
      continue;
    }
    const existing = index.get(row.UserMarkGuid);
    if (!existing) {
      const id = run(
        db,
        "INSERT INTO UserMark(ColorIndex, LocationId, StyleIndex, UserMarkGuid," +
          " Version) VALUES (?, ?, ?, ?, ?)",
        [row.ColorIndex, loc, row.StyleIndex, row.UserMarkGuid, row.Version]
      );
      map.set(row.UserMarkId, id);
      index.set(row.UserMarkGuid, { ...row, UserMarkId: id, LocationId: loc });
      sr.bump("added", "UserMark");
      copyBlockRanges(db, src, row.UserMarkId, id, sr, false);
      continue;
    }

    map.set(row.UserMarkId, existing.UserMarkId);
    if ((row.Version || 0) > (existing.Version || 0)) {
      db.run(
        "UPDATE UserMark SET ColorIndex = ?, StyleIndex = ?, LocationId = ?," +
          " Version = ? WHERE UserMarkId = ?",
        [row.ColorIndex, row.StyleIndex, loc, row.Version, existing.UserMarkId]
      );
      db.run("DELETE FROM BlockRange WHERE UserMarkId = ?", [existing.UserMarkId]);
      copyBlockRanges(db, src, row.UserMarkId, existing.UserMarkId, sr, false);
      existing.Version = row.Version;
      sr.bump("updated", "UserMark");
    } else {
      sr.bump("reused", "UserMark");
      copyBlockRanges(db, src, row.UserMarkId, existing.UserMarkId, sr, true);
    }
  }
  return map;
}

function copyBlockRanges(db, src, sourceMark, targetMark, sr, additive) {
  const existing = new Set(
    additive
      ? all(db, "SELECT * FROM BlockRange WHERE UserMarkId = ?", [targetMark]).map((r) =>
          key(r.BlockType, r.Identifier, r.StartToken, r.EndToken)
        )
      : []
  );
  for (const row of all(src, "SELECT * FROM BlockRange WHERE UserMarkId = ?", [
    sourceMark,
  ])) {
    const k = key(row.BlockType, row.Identifier, row.StartToken, row.EndToken);
    if (existing.has(k)) {
      sr.bump("reused", "BlockRange");
      continue;
    }
    db.run(
      "INSERT INTO BlockRange(BlockType, Identifier, StartToken, EndToken," +
        " UserMarkId) VALUES (?, ?, ?, ?, ?)",
      [row.BlockType, row.Identifier, row.StartToken, row.EndToken, targetMark]
    );
    existing.add(k);
    sr.bump("added", "BlockRange");
  }
}

function mergeNotes(db, src, marks, locations, sr) {
  const index = new Map(all(db, "SELECT * FROM Note").map((r) => [r.Guid, r]));

  for (const row of all(src, "SELECT * FROM Note")) {
    const mark = row.UserMarkId ? marks.get(row.UserMarkId) ?? null : null;
    const loc = row.LocationId ? locations.get(row.LocationId) ?? null : null;
    const existing = index.get(row.Guid);

    if (!existing) {
      const id = run(
        db,
        "INSERT INTO Note(Guid, UserMarkId, LocationId, Title, Content," +
          " LastModified, Created, BlockType, BlockIdentifier)" +
          " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
          row.Guid,
          mark,
          loc,
          row.Title,
          row.Content,
          row.LastModified,
          row.Created,
          row.BlockType,
          row.BlockIdentifier,
        ]
      );
      index.set(row.Guid, { ...row, NoteId: id });
      sr.bump("added", "Note");
      continue;
    }

    const sourceModified = row.LastModified || "";
    const targetModified = existing.LastModified || "";
    const same =
      (row.Title || "") === (existing.Title || "") &&
      (row.Content || "") === (existing.Content || "");

    if (same || sourceModified <= targetModified) {
      sr.bump("reused", "Note");
      if (!same && sourceModified === targetModified) {
        sr.conflict(
          "Note",
          `a note differs between devices but both carry the same date ` +
            `(${sourceModified})`,
          "kept the copy from the newest backup"
        );
      }
      continue;
    }

    db.run(
      "UPDATE Note SET UserMarkId = ?, LocationId = ?, Title = ?, Content = ?," +
        " LastModified = ?, BlockType = ?, BlockIdentifier = ? WHERE NoteId = ?",
      [
        mark,
        loc,
        row.Title,
        row.Content,
        sourceModified,
        row.BlockType,
        row.BlockIdentifier,
        existing.NoteId,
      ]
    );
    existing.LastModified = sourceModified;
    existing.Title = row.Title;
    existing.Content = row.Content;
    sr.bump("updated", "Note");
    sr.conflict(
      "Note",
      `a note was edited on both devices (${targetModified} vs ${sourceModified})`,
      "took the newer copy"
    );
  }
}

function mergeBookmarks(db, src, locations, sr) {
  const rows = all(db, "SELECT * FROM Bookmark");
  const index = new Set(
    rows.map((r) =>
      key(r.PublicationLocationId, r.LocationId, r.BlockType, r.BlockIdentifier)
    )
  );
  const usedSlots = new Map();
  for (const r of rows) {
    if (!usedSlots.has(r.PublicationLocationId)) {
      usedSlots.set(r.PublicationLocationId, new Set());
    }
    usedSlots.get(r.PublicationLocationId).add(r.Slot);
  }

  for (const row of all(src, "SELECT * FROM Bookmark")) {
    const pub = locations.get(row.PublicationLocationId);
    const loc = locations.get(row.LocationId);
    if (pub === undefined || loc === undefined) {
      sr.bump("skipped", "Bookmark");
      continue;
    }
    const k = key(pub, loc, row.BlockType, row.BlockIdentifier);
    if (index.has(k)) {
      sr.bump("reused", "Bookmark");
      continue;
    }

    if (!usedSlots.has(pub)) usedSlots.set(pub, new Set());
    const slots = usedSlots.get(pub);
    let slot = null;
    for (let s = 0; s <= MAX_BOOKMARK_SLOT; s++) {
      if (!slots.has(s)) {
        slot = s;
        break;
      }
    }
    if (slot === null) {
      sr.bump("skipped", "Bookmark");
      sr.conflict(
        "Bookmark",
        `this publication already uses all ${MAX_BOOKMARK_SLOT + 1} bookmark slots`,
        `could not add "${row.Title}"`
      );
      continue;
    }

    db.run(
      "INSERT INTO Bookmark(LocationId, PublicationLocationId, Slot, Title," +
        " Snippet, BlockType, BlockIdentifier) VALUES (?, ?, ?, ?, ?, ?, ?)",
      [loc, pub, slot, row.Title, row.Snippet, row.BlockType, row.BlockIdentifier]
    );
    slots.add(slot);
    index.add(k);
    sr.bump("added", "Bookmark");
  }
}

function mergeInputFields(db, src, locations, policy, sr) {
  const index = new Map(
    all(db, "SELECT * FROM InputField").map((r) => [
      key(r.LocationId, r.TextTag),
      r.Value,
    ])
  );

  for (const row of all(src, "SELECT * FROM InputField")) {
    const loc = locations.get(row.LocationId);
    if (loc === undefined) {
      sr.bump("skipped", "InputField");
      continue;
    }
    const k = key(loc, row.TextTag);
    if (!index.has(k)) {
      db.run("INSERT INTO InputField(LocationId, TextTag, Value) VALUES (?, ?, ?)", [
        loc,
        row.TextTag,
        row.Value,
      ]);
      index.set(k, row.Value);
      sr.bump("added", "InputField");
      continue;
    }
    if (index.get(k) === row.Value) {
      sr.bump("reused", "InputField");
      continue;
    }

    let resolution;
    if (policy === "overwrite") {
      db.run("UPDATE InputField SET Value = ? WHERE LocationId = ? AND TextTag = ?", [
        row.Value,
        loc,
        row.TextTag,
      ]);
      index.set(k, row.Value);
      sr.bump("updated", "InputField");
      resolution = "took the other device's answer";
    } else {
      sr.bump("reused", "InputField");
      resolution = "kept the newest backup's answer";
    }
    sr.conflict(
      "InputField",
      "a study answer differs between devices, and JW Library records no date for it",
      resolution
    );
  }
}

function mergeTags(db, src, sr) {
  const index = new Map(
    all(db, "SELECT * FROM Tag").map((r) => [key(r.Type, r.Name), r.TagId])
  );
  const map = new Map();
  for (const row of all(src, "SELECT * FROM Tag")) {
    const k = key(row.Type, row.Name);
    if (index.has(k)) {
      map.set(row.TagId, index.get(k));
      sr.bump("reused", "Tag");
      continue;
    }
    const id = run(db, "INSERT INTO Tag(Type, Name) VALUES (?, ?)", [row.Type, row.Name]);
    index.set(k, id);
    map.set(row.TagId, id);
    sr.bump("added", "Tag");
  }
  return map;
}

function mergePlaylistItems(db, src, accuracy, mediaPaths, sr) {
  const targetCtx = mediaContext(db);
  const sourceCtx = mediaContext(src);
  const targetOwning = owningTags(db);
  const sourceOwning = owningTags(src);

  const index = new Map();
  for (const row of all(db, "SELECT * FROM PlaylistItem")) {
    const k = playlistItemKey(db, row, targetOwning.get(row.PlaylistItemId), targetCtx);
    if (!index.has(k)) index.set(k, row.PlaylistItemId);
  }

  const map = new Map();
  for (const row of all(src, "SELECT * FROM PlaylistItem")) {
    const k = playlistItemKey(src, row, sourceOwning.get(row.PlaylistItemId), sourceCtx);
    if (index.has(k)) {
      map.set(row.PlaylistItemId, index.get(k));
      sr.bump("reused", "PlaylistItem");
      continue;
    }

    let thumb = row.ThumbnailFilePath || null;
    if (thumb) {
      thumb = mediaPaths.get(thumb) || thumb;
      if (!scalar(db, "SELECT 1 FROM IndependentMedia WHERE FilePath = ?", [thumb])) {
        thumb = null;
      }
    }

    const id = run(
      db,
      "INSERT INTO PlaylistItem(Label, StartTrimOffsetTicks, EndTrimOffsetTicks," +
        " Accuracy, EndAction, ThumbnailFilePath) VALUES (?, ?, ?, ?, ?, ?)",
      [
        row.Label,
        row.StartTrimOffsetTicks ?? null,
        row.EndTrimOffsetTicks ?? null,
        accuracy.get(row.Accuracy) ?? row.Accuracy,
        row.EndAction,
        thumb,
      ]
    );
    map.set(row.PlaylistItemId, id);
    index.set(k, id);
    sr.bump("added", "PlaylistItem");
  }
  return map;
}

function mergePlaylistChildren(db, src, items, mediaIds, locations, sr) {
  for (const row of all(src, "SELECT * FROM PlaylistItemIndependentMediaMap")) {
    const item = items.get(row.PlaylistItemId);
    const media = mediaIds.get(row.IndependentMediaId);
    if (item === undefined || media === undefined) {
      sr.bump("skipped", "PlaylistItemIndependentMediaMap");
      continue;
    }
    const existed = scalar(
      db,
      "SELECT 1 FROM PlaylistItemIndependentMediaMap" +
        " WHERE PlaylistItemId = ? AND IndependentMediaId = ?",
      [item, media]
    );
    if (existed) {
      sr.bump("reused", "PlaylistItemIndependentMediaMap");
      continue;
    }
    db.run(
      "INSERT INTO PlaylistItemIndependentMediaMap(PlaylistItemId," +
        " IndependentMediaId, DurationTicks) VALUES (?, ?, ?)",
      [item, media, row.DurationTicks]
    );
    sr.bump("added", "PlaylistItemIndependentMediaMap");
  }

  for (const row of all(src, "SELECT * FROM PlaylistItemLocationMap")) {
    const item = items.get(row.PlaylistItemId);
    const loc = locations.get(row.LocationId);
    if (item === undefined || loc === undefined) {
      sr.bump("skipped", "PlaylistItemLocationMap");
      continue;
    }
    const existed = scalar(
      db,
      "SELECT 1 FROM PlaylistItemLocationMap WHERE PlaylistItemId = ? AND LocationId = ?",
      [item, loc]
    );
    if (existed) {
      sr.bump("reused", "PlaylistItemLocationMap");
      continue;
    }
    db.run(
      "INSERT INTO PlaylistItemLocationMap(PlaylistItemId, LocationId," +
        " MajorMultimediaType, BaseDurationTicks) VALUES (?, ?, ?, ?)",
      [item, loc, row.MajorMultimediaType, row.BaseDurationTicks ?? null]
    );
    sr.bump("added", "PlaylistItemLocationMap");
  }

  const markerMap = new Map();
  for (const row of all(src, "SELECT * FROM PlaylistItemMarker")) {
    const item = items.get(row.PlaylistItemId);
    if (item === undefined) {
      sr.bump("skipped", "PlaylistItemMarker");
      continue;
    }
    const existing = scalar(
      db,
      "SELECT PlaylistItemMarkerId FROM PlaylistItemMarker" +
        " WHERE PlaylistItemId = ? AND StartTimeTicks = ?",
      [item, row.StartTimeTicks]
    );
    if (existing) {
      markerMap.set(row.PlaylistItemMarkerId, existing);
      sr.bump("reused", "PlaylistItemMarker");
      continue;
    }
    const id = run(
      db,
      "INSERT INTO PlaylistItemMarker(PlaylistItemId, Label, StartTimeTicks," +
        " DurationTicks, EndTransitionDurationTicks) VALUES (?, ?, ?, ?, ?)",
      [
        item,
        row.Label,
        row.StartTimeTicks,
        row.DurationTicks,
        row.EndTransitionDurationTicks,
      ]
    );
    markerMap.set(row.PlaylistItemMarkerId, id);
    sr.bump("added", "PlaylistItemMarker");
  }

  for (const row of all(src, "SELECT * FROM PlaylistItemMarkerBibleVerseMap")) {
    const marker = markerMap.get(row.PlaylistItemMarkerId);
    if (marker === undefined) continue;
    db.run(
      "INSERT OR IGNORE INTO PlaylistItemMarkerBibleVerseMap(PlaylistItemMarkerId," +
        " VerseId) VALUES (?, ?)",
      [marker, row.VerseId]
    );
    sr.bump("added", "PlaylistItemMarkerBibleVerseMap");
  }

  for (const row of all(src, "SELECT * FROM PlaylistItemMarkerParagraphMap")) {
    const marker = markerMap.get(row.PlaylistItemMarkerId);
    if (marker === undefined) continue;
    db.run(
      "INSERT OR IGNORE INTO PlaylistItemMarkerParagraphMap(PlaylistItemMarkerId," +
        " MepsDocumentId, ParagraphIndex, MarkerIndexWithinParagraph)" +
        " VALUES (?, ?, ?, ?)",
      [marker, row.MepsDocumentId, row.ParagraphIndex, row.MarkerIndexWithinParagraph]
    );
    sr.bump("added", "PlaylistItemMarkerParagraphMap");
  }
}

function mergeTagMaps(db, src, tags, items, locations, sr) {
  const noteByGuid = new Map(all(db, "SELECT * FROM Note").map((r) => [r.Guid, r.NoteId]));
  const sourceNoteGuid = new Map(
    all(src, "SELECT * FROM Note").map((r) => [r.NoteId, r.Guid])
  );

  const existing = new Set();
  const nextPosition = new Map();
  for (const r of all(db, "SELECT * FROM TagMap")) {
    existing.add(key(r.TagId, r.PlaylistItemId, r.LocationId, r.NoteId));
    nextPosition.set(r.TagId, Math.max(nextPosition.get(r.TagId) ?? -1, r.Position));
  }

  for (const row of all(src, "SELECT * FROM TagMap ORDER BY TagId, Position")) {
    const tag = tags.get(row.TagId);
    if (tag === undefined) {
      sr.bump("skipped", "TagMap");
      continue;
    }

    const item = row.PlaylistItemId ? items.get(row.PlaylistItemId) ?? null : null;
    const loc = row.LocationId ? locations.get(row.LocationId) ?? null : null;
    let note = null;
    if (row.NoteId) {
      const guid = sourceNoteGuid.get(row.NoteId);
      note = guid ? noteByGuid.get(guid) ?? null : null;
    }

    if (
      (row.PlaylistItemId && item === null) ||
      (row.LocationId && loc === null) ||
      (row.NoteId && note === null)
    ) {
      sr.bump("skipped", "TagMap");
      continue;
    }

    const k = key(tag, item, loc, note);
    if (existing.has(k)) {
      sr.bump("reused", "TagMap");
      continue;
    }

    const position = (nextPosition.get(tag) ?? -1) + 1;
    db.run(
      "INSERT INTO TagMap(PlaylistItemId, LocationId, NoteId, TagId, Position)" +
        " VALUES (?, ?, ?, ?, ?)",
      [item, loc, note, tag, position]
    );
    nextPosition.set(tag, position);
    existing.add(k);
    sr.bump("added", "TagMap");
  }
}

export { all, scalar };
