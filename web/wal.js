// Applying a SQLite write-ahead log to a database image.
//
// This exists because of a trap. JW Library keeps its database in WAL mode, and
// on a real device the main userData.db file can be a 4 KB empty shell while
// every note, highlight and playlist lives in the 1.7 MB userData.db-wal beside
// it. Anyone who copies only userData.db gets a library with no tables in it --
// and would destroy their real one by restoring it.
//
// sql.js takes a single byte array and knows nothing about a separate log, so
// the log has to be folded in first. This is SQLite's own recovery procedure:
// walk the frames, keep the ones whose salt and checksum say they belong, and
// replay them up to the last commit.
//
// Format reference: https://sqlite.org/fileformat2.html#walformat

const WAL_HEADER_SIZE = 32;
const FRAME_HEADER_SIZE = 24;
const MAGIC_LITTLE = 0x377f0682;
const MAGIC_BIG = 0x377f0683;

export class WalError extends Error {}

/**
 * SQLite's checksum: a running pair of 32-bit words over 8-byte chunks.
 *
 * Byte order follows the WAL magic, not the platform.
 */
function checksum(view, start, end, big, s0, s1) {
  for (let i = start; i < end; i += 8) {
    s0 = (s0 + view.getUint32(i, !big) + s1) >>> 0;
    s1 = (s1 + view.getUint32(i + 4, !big) + s0) >>> 0;
  }
  return [s0, s1];
}

/**
 * Fold `wal` into `db` and return the resulting database image.
 *
 * Both arguments are Uint8Arrays. When the log holds nothing applicable, the
 * database is returned unchanged.
 */
export function applyWal(db, wal) {
  if (!wal || wal.length < WAL_HEADER_SIZE) return db;

  const walView = new DataView(wal.buffer, wal.byteOffset, wal.byteLength);
  const magic = walView.getUint32(0, false);
  if (magic !== MAGIC_LITTLE && magic !== MAGIC_BIG) {
    throw new WalError("this is not a SQLite write-ahead log");
  }
  const big = magic === MAGIC_BIG;

  const pageSize = walView.getUint32(8, false);
  if (pageSize < 512 || (pageSize & (pageSize - 1)) !== 0) {
    throw new WalError(`the log declares an impossible page size (${pageSize})`);
  }
  const salt1 = walView.getUint32(16, false);
  const salt2 = walView.getUint32(20, false);

  // The frame checksums chain on from the header's own.
  let s0 = walView.getUint32(24, false);
  let s1 = walView.getUint32(28, false);

  const frameSize = FRAME_HEADER_SIZE + pageSize;
  const pages = new Map(); // page number -> offset of its data in the log
  let committedPages = null; // page count declared by the last commit frame
  let committedSoFar = null; // snapshot of `pages` at that commit

  for (let at = WAL_HEADER_SIZE; at + frameSize <= wal.length; at += frameSize) {
    // A frame from an earlier generation of the log: everything after it is
    // stale too, so stop rather than skip.
    if (
      walView.getUint32(at + 8, false) !== salt1 ||
      walView.getUint32(at + 12, false) !== salt2
    ) {
      break;
    }

    // Checksum covers the first 8 bytes of the frame header and then the page.
    let [c0, c1] = checksum(walView, at, at + 8, big, s0, s1);
    [c0, c1] = checksum(
      walView,
      at + FRAME_HEADER_SIZE,
      at + frameSize,
      big,
      c0,
      c1
    );
    if (
      c0 !== walView.getUint32(at + 16, false) ||
      c1 !== walView.getUint32(at + 20, false)
    ) {
      break; // torn or truncated write; nothing beyond it can be trusted
    }
    s0 = c0;
    s1 = c1;

    const pageNumber = walView.getUint32(at, false);
    pages.set(pageNumber, at + FRAME_HEADER_SIZE);

    const dbSize = walView.getUint32(at + 4, false);
    if (dbSize !== 0) {
      // A commit. Only what is committed may be applied.
      committedPages = dbSize;
      committedSoFar = new Map(pages);
    }
  }

  if (committedSoFar === null) return db;

  const out = new Uint8Array(committedPages * pageSize);
  out.set(db.subarray(0, Math.min(db.length, out.length)));
  for (const [pageNumber, offset] of committedSoFar) {
    if (pageNumber < 1 || pageNumber > committedPages) continue;
    out.set(wal.subarray(offset, offset + pageSize), (pageNumber - 1) * pageSize);
  }
  return out;
}

/** Whether a file name is the write-ahead log of `dbName`. */
export function isWalFor(name, dbName) {
  return name === `${dbName}-wal`;
}

/** Whether a file name is a SQLite sidecar that carries no data of its own. */
export function isSharedMemory(name) {
  return name.endsWith("-shm");
}
