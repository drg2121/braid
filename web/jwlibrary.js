// Reading and writing .jwlibrary archives in the browser.
//
// A phone backup runs to hundreds of megabytes, and Safari on an iPhone will
// not hold that in memory twice. So nothing here decompresses more than it has
// to: the database and the manifest are read out, and every media file is
// copied from input to output as its already-compressed bytes, referenced
// through Blob slices that the browser keeps on disk rather than in memory.

const EOCD_SIGNATURE = 0x06054b50;
const CENTRAL_SIGNATURE = 0x02014b50;
const LOCAL_SIGNATURE = 0x04034b50;
const ZIP64_EOCD_LOCATOR = 0x07064b50;

const DB_NAME = "userData.db";
const MANIFEST_NAME = "manifest.json";

export class ArchiveError extends Error {}

async function sliceBytes(blob, start, end) {
  return new Uint8Array(await blob.slice(start, end).arrayBuffer());
}

function u16(view, offset) {
  return view.getUint16(offset, true);
}

function u32(view, offset) {
  return view.getUint32(offset, true);
}

/**
 * Parse a zip's central directory.
 *
 * Returns entries carrying everything needed either to read a member or to
 * copy it verbatim into another archive.
 */
export async function readDirectory(blob) {
  const tailLength = Math.min(blob.size, 66000);
  const tail = await sliceBytes(blob, blob.size - tailLength, blob.size);
  const tailView = new DataView(tail.buffer);

  let eocd = -1;
  for (let i = tail.length - 22; i >= 0; i--) {
    if (u32(tailView, i) === EOCD_SIGNATURE) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) {
    throw new ArchiveError("this file is not a .jwlibrary archive");
  }
  if (eocd >= 20 && u32(tailView, eocd - 20) === ZIP64_EOCD_LOCATOR) {
    throw new ArchiveError("this archive uses the zip64 format, which is not supported");
  }

  const count = u16(tailView, eocd + 10);
  const directorySize = u32(tailView, eocd + 12);
  const directoryOffset = u32(tailView, eocd + 16);

  const directory = await sliceBytes(
    blob,
    directoryOffset,
    directoryOffset + directorySize
  );
  const view = new DataView(directory.buffer);
  const decoder = new TextDecoder();

  const entries = [];
  let at = 0;
  for (let n = 0; n < count; n++) {
    if (u32(view, at) !== CENTRAL_SIGNATURE) {
      throw new ArchiveError("this archive's directory is damaged");
    }
    const flags = u16(view, at + 8);
    const nameLength = u16(view, at + 28);
    const extraLength = u16(view, at + 30);
    const commentLength = u16(view, at + 32);
    const name = decoder.decode(directory.subarray(at + 46, at + 46 + nameLength));

    if (flags & 0x8) {
      throw new ArchiveError(`${name} uses a streaming zip feature that is not supported`);
    }

    entries.push({
      name,
      method: u16(view, at + 10),
      crc32: u32(view, at + 16),
      compressedSize: u32(view, at + 20),
      uncompressedSize: u32(view, at + 24),
      modTime: u16(view, at + 12),
      modDate: u16(view, at + 14),
      localHeaderOffset: u32(view, at + 42),
    });
    at += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

/** Where an entry's compressed bytes actually begin, per its local header. */
async function dataOffset(blob, entry) {
  const header = await sliceBytes(
    blob,
    entry.localHeaderOffset,
    entry.localHeaderOffset + 30
  );
  const view = new DataView(header.buffer);
  if (u32(view, 0) !== LOCAL_SIGNATURE) {
    throw new ArchiveError(`${entry.name} is not where the archive says it is`);
  }
  return entry.localHeaderOffset + 30 + u16(view, 26) + u16(view, 28);
}

/** The entry's compressed bytes, as a lazy Blob slice -- nothing is read yet. */
export async function rawSlice(blob, entry) {
  const start = await dataOffset(blob, entry);
  return blob.slice(start, start + entry.compressedSize);
}

/** Read and decompress one entry. Only use this for small members. */
export async function readEntry(blob, entry) {
  const slice = await rawSlice(blob, entry);
  if (entry.method === 0) {
    return new Uint8Array(await slice.arrayBuffer());
  }
  if (entry.method !== 8) {
    throw new ArchiveError(`${entry.name} uses an unsupported compression method`);
  }
  const stream = slice.stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

// -- writing ---------------------------------------------------------------

function dosDateTime(date = new Date()) {
  const time =
    (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1);
  const day =
    ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { time, day };
}

let crcTable = null;
function crc32(bytes) {
  if (!crcTable) {
    crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c;
    }
  }
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) {
    crc = crcTable[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

async function deflateRaw(bytes) {
  const stream = new Blob([bytes])
    .stream()
    .pipeThrough(new CompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/**
 * Builds a zip out of Blob parts.
 *
 * Members added with `copyFrom` never pass through memory: their compressed
 * bytes stay in the source file and the output Blob merely points at them.
 */
export class ZipBuilder {
  constructor() {
    this.parts = [];
    this.central = [];
    this.offset = 0;
    this.encoder = new TextEncoder();
  }

  #push(name, { crc, compressedSize, uncompressedSize, method, dataPart }) {
    const nameBytes = this.encoder.encode(name);
    const { time, day } = dosDateTime();

    const local = new Uint8Array(30 + nameBytes.length);
    const localView = new DataView(local.buffer);
    localView.setUint32(0, LOCAL_SIGNATURE, true);
    localView.setUint16(4, 20, true); // version needed
    localView.setUint16(6, 0x800, true); // UTF-8 names
    localView.setUint16(8, method, true);
    localView.setUint16(10, time, true);
    localView.setUint16(12, day, true);
    localView.setUint32(14, crc, true);
    localView.setUint32(18, compressedSize, true);
    localView.setUint32(22, uncompressedSize, true);
    localView.setUint16(26, nameBytes.length, true);
    localView.setUint16(28, 0, true);
    local.set(nameBytes, 30);

    this.parts.push(local, dataPart);

    const central = new Uint8Array(46 + nameBytes.length);
    const centralView = new DataView(central.buffer);
    centralView.setUint32(0, CENTRAL_SIGNATURE, true);
    centralView.setUint16(4, 20, true); // version made by
    centralView.setUint16(6, 20, true); // version needed
    centralView.setUint16(8, 0x800, true);
    centralView.setUint16(10, method, true);
    centralView.setUint16(12, time, true);
    centralView.setUint16(14, day, true);
    centralView.setUint32(16, crc, true);
    centralView.setUint32(20, compressedSize, true);
    centralView.setUint32(24, uncompressedSize, true);
    centralView.setUint16(28, nameBytes.length, true);
    centralView.setUint32(42, this.offset, true);
    central.set(nameBytes, 46);
    this.central.push(central);

    this.offset += local.length + compressedSize;
  }

  /** Add a member from bytes held in memory. */
  async add(name, bytes) {
    const compressed = await deflateRaw(bytes);
    this.#push(name, {
      crc: crc32(bytes),
      compressedSize: compressed.length,
      uncompressedSize: bytes.length,
      method: 8,
      dataPart: compressed,
    });
  }

  /**
   * Add a member by pointing at another archive's already-compressed bytes.
   *
   * The checksum and sizes come from that archive's directory, because the
   * bytes are identical -- so nothing has to be decompressed to know them.
   */
  copyFrom(name, entry, slice) {
    this.#push(name, {
      crc: entry.crc32,
      compressedSize: entry.compressedSize,
      uncompressedSize: entry.uncompressedSize,
      method: entry.method,
      dataPart: slice,
    });
  }

  finish(mimeType = "application/octet-stream") {
    const directoryOffset = this.offset;
    const directorySize = this.central.reduce((n, part) => n + part.length, 0);

    const eocd = new Uint8Array(22);
    const view = new DataView(eocd.buffer);
    view.setUint32(0, EOCD_SIGNATURE, true);
    view.setUint16(8, this.central.length, true);
    view.setUint16(10, this.central.length, true);
    view.setUint32(12, directorySize, true);
    view.setUint32(16, directoryOffset, true);

    return new Blob([...this.parts, ...this.central, eocd], { type: mimeType });
  }
}

// -- the .jwlibrary layer --------------------------------------------------

/**
 * Format a digest the way JW Library does.
 *
 * The app renders each byte with a %x-style format instead of %02x, so bytes
 * below 0x10 lose their leading zero. Matching that exactly is what lets the
 * same media file be recognised across devices.
 */
export function jwHex(bytes) {
  let out = "";
  for (const b of bytes) out += b.toString(16);
  return out;
}

export async function jwHashOf(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return jwHex(new Uint8Array(digest));
}

/** One opened backup: its manifest, its database bytes, and its media entries. */
export class BackupFile {
  constructor(file, entries, manifest, dbEntry) {
    this.file = file;
    this.entries = entries;
    this.manifest = manifest;
    this.dbEntry = dbEntry;
  }

  static async open(file) {
    const entries = await readDirectory(file);
    const byName = new Map(entries.map((e) => [e.name, e]));

    const manifestEntry = byName.get(MANIFEST_NAME);
    if (!manifestEntry) {
      throw new ArchiveError(`${file.name} has no ${MANIFEST_NAME}`);
    }
    const manifest = JSON.parse(
      new TextDecoder().decode(await readEntry(file, manifestEntry))
    );

    const dbName = manifest?.userDataBackup?.databaseName || DB_NAME;
    const dbEntry = byName.get(dbName);
    if (!dbEntry) {
      throw new ArchiveError(`${file.name} has no ${dbName}`);
    }
    return new BackupFile(file, entries, manifest, dbEntry);
  }

  get deviceName() {
    return this.manifest?.userDataBackup?.deviceName || "";
  }

  get schemaVersion() {
    return this.manifest?.userDataBackup?.schemaVersion ?? 0;
  }

  get lastModified() {
    return (
      this.manifest?.userDataBackup?.lastModifiedDate ||
      this.manifest?.creationDate ||
      ""
    );
  }

  async database() {
    return readEntry(this.file, this.dbEntry);
  }

  /** Every member except the database and the manifest. */
  mediaEntries() {
    const skip = new Set([this.dbEntry.name, MANIFEST_NAME]);
    return this.entries.filter((e) => !skip.has(e.name) && !e.name.endsWith("/"));
  }

  entry(name) {
    return this.entries.find((e) => e.name === name) || null;
  }
}

export { DB_NAME, MANIFEST_NAME };
