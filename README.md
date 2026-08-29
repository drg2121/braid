# jwsync

Merge JW Library backups from several devices into a single file you can restore
everywhere, so your notes, highlights, bookmarks, tags and playlists stop living
on one device at a time.

JW Library has no cross-device sync for personal study data. It can export a
`.jwlibrary` backup and restore one, but restoring **replaces** everything on the
target device. `jwsync` sits in between: it takes the backups from your phone,
tablet and laptop, merges them into one, and gives you a file that is safe to
restore on all of them.

```
phone.jwlibrary  ─┐
tablet.jwlibrary ─┼─▶ jwsync ─▶ merged.jwlibrary ─▶ restore on every device
laptop.jwlibrary ─┘
```

## What you should know first

- **The merge only ever adds.** Nothing is deleted. That is deliberate — it is
  what makes the tool safe to run repeatedly — but it has one consequence worth
  understanding: if you delete a note on your phone and then merge with an older
  tablet backup that still has it, the note comes back. Delete on every device,
  or delete after the merge.
- **Keep your original backups.** `jwsync` never modifies its inputs; it writes a
  new file. Keep the per-device exports until you have confirmed the merged file
  restores correctly.
- **Restore replaces.** When JW Library restores a backup it wipes the device's
  existing personal data first. Restore the *merged* file, not one device's own
  backup, or that device loses whatever the others contributed.
- This is an independent project. It is not affiliated with, endorsed by, or
  supported by the publishers of JW Library.

## In the browser, with no computer at all

Most people have a phone and a tablet and nothing else, so the merge also exists
as a web page that does the whole thing client-side: `web/` is a static site that
opens the backups, merges them and writes the result without a byte leaving the
device. It works on an iPad, an iPhone, a Mac or a PC, offline once loaded.

```bash
python3 -m http.server --directory web    # try it locally
python3 web/build.py                       # one self-contained file in dist/
```

`web/build.py` inlines every module and the SQLite WebAssembly build into a
single ~1 MB HTML file that can be emailed or AirDropped and opened straight from
Files. Because bundling drops every module into one scope, it refuses to build
when two modules declare the same top-level name -- a collision that otherwise
surfaces only as a dead page and a `SyntaxError` in a console nobody has open.

The page remembers the combined library in IndexedDB, per person, so the next
round needs only a fresh backup from the device that was actually used rather
than one from every device. Several people can share one browser without their
libraries ever mixing, which matters on a shared tablet. `web/store.test.mjs`
covers that with `fake-indexeddb`:

```bash
npm install --no-save fake-indexeddb && npm test
```

Two things make it fast enough for a 210 MB backup on a phone. Media is copied
between archives as its already-compressed bytes, referenced through `Blob`
slices the browser keeps on disk, so nothing but the database is ever decompressed
or held in memory; and the checksum and sizes come from the source archive's own
directory, because the bytes are identical. Merging a 210 MB and a 51 MB backup
takes about half a second.

The merge is implemented twice -- `src/jwsync/merge.py` and `web/merge.js` --
which is a drift risk, so `tests/test_browser_parity.py` runs both engines over
the same libraries and fails if their row counts, tags or verification results
differ.

## Install

**If you are not a developer**, read [GUIDE.md](GUIDE.md) instead — it covers
everything without a terminal. In short: download the ZIP, unzip it, and
double-click a launcher in `launchers/`.

Python 3.9 or newer, no third-party dependencies. macOS ships a suitable Python
already, so on a Mac there is nothing to install at all.

```bash
pip install -e .
```

Or run it straight from a checkout without installing:

```bash
python -m jwsync --help
```

## Use it

### Point and click

```bash
jwsync serve
```

Opens `http://127.0.0.1:8765` — pick a folder, add this computer's own library
with one button, merge, and put the result back. Binds to localhost only. This is
what the launchers in `launchers/` start.

### Look at a backup

```bash
jwsync inspect ~/Downloads/UserdataBackup_2026-08-29_iPhone.jwlibrary
```

```
UserdataBackup_2026-08-29_iPhone.jwlibrary
  device        iPhone
  schema        v16
  lastModified  2026-08-29T17:32:51+0300
  media files   70
    Location                              314
    UserMark                             4923
    Note                                   33
    ...
```

### Merge two or more backups

```bash
jwsync merge phone.jwlibrary tablet.jwlibrary -o merged.jwlibrary
```

The most recently modified backup becomes the base, so argument order does not
matter. The report tells you exactly what happened:

```
source  : UserdataBackup_2026-08-29_iPad.jwlibrary  [iPad]  modified 2026-08-04T18:20:02+0300
  added   BlockRange=1  Location=1  PlaylistItem=22  Tag=2  TagMap=22  UserMark=1
  reused  IndependentMedia=13  Location=2
  media   added=0  reused=13  renamed=0
```

### Keep it merging by itself

This is the flow to actually use day to day. `watch` sits on a folder your
devices already sync and rebuilds one merged file, under one unchanging name,
whenever any device drops a new backup in:

```bash
jwsync watch ~/Library/Mobile\ Documents/com~apple~CloudDocs/JW\ backups
```

```
[19:58:04] watching /Users/you/…/JW backups every 30s (Ctrl-C to stop)
[19:58:11] change detected, letting it settle
[19:58:19] merged 2 backups, 71 new rows, verified -> JW Library MERGED.jwlibrary
```

The output is always called **`JW Library MERGED.jwlibrary`**, so the file you
restore on each device never changes name — the cloud provider simply updates it
in place. Dated copies of every merge are kept in `_jwsync_history/`, and what
has already been merged is remembered there too, so restarting the watcher (or
running `--once` from cron) never redoes finished work.

Then make it start at login:

```bash
jwsync install-agent ~/Library/Mobile\ Documents/com~apple~CloudDocs/JW\ backups
```

That writes a launchd agent on macOS, a systemd user unit on Linux, or prints
the Task Scheduler command on Windows. It does **not** start it — the command
prints the one line that does, so nothing begins running at login without you
asking.

#### On this computer: no taps at all

On a Mac or PC the library is not something you export — it is a live SQLite
database inside the app's folder, and `jwsync` can read and write it directly:

```bash
jwsync status                      # find it, show what is in it
jwsync pull ~/JW\ backups          # export it — safe while JW Library is open
jwsync push "~/JW backups/JW Library MERGED.jwlibrary" --yes   # app must be closed
```

`watch` does both for you:

```bash
jwsync watch ~/JW\ backups --with-local --push-local
```

`--with-local` exports this computer's library before every merge. `--push-local`
installs the merged result back into it afterwards, and is skipped with a message
whenever JW Library is open, because writing to a live WAL database can corrupt
it. The previous library is always copied aside first, into
`~/jwsync-safety-copies/`.

So on the computer the whole round trip is automatic. Phones and tablets are
what still need taps.

#### What this can and cannot automate

JW Library has no API, no URL scheme and no Shortcuts actions, and a phone's app
storage is not reachable from a computer. So on **phones and tablets**, export
and restore stay manual. Everywhere else it is automatic:

| Step | Mac / PC | Phone / tablet |
| --- | --- | --- |
| Get the library out | `jwsync pull` | You — Personal Study ▸ ⤒ ▸ Create Backup, save into the shared folder |
| Notice the new backup | `jwsync watch` | `jwsync watch` |
| Merge everything | `jwsync watch` | `jwsync watch` |
| Check nothing was lost | `jwsync watch` | `jwsync watch` |
| Move it back to the device | your cloud provider | your cloud provider |
| Put the library back in | `jwsync push` | You — Personal Study ▸ ⤒ ▸ Restore Backup |

A round of syncing therefore costs nothing on the computer and a handful of taps
per phone or tablet. Export where you made changes, restore where you want them.

Two things worth setting up once:

- On a phone, export **straight into the shared folder** from the share sheet
  (Files ▸ iCloud Drive ▸ your folder). That removes the transfer step entirely.
- If a device's backup shows as a `.icloud` placeholder, the watcher says so and
  waits rather than merging a half-downloaded file. Marking the folder *Keep
  Downloaded* avoids it.

### Merge a folder once



The workflow that actually keeps three devices in step: point every device's
backup export at one folder that iCloud Drive, Google Drive or Dropbox already
syncs, then run:

```bash
jwsync sync ~/Library/Mobile\ Documents/com~apple~CloudDocs/JW\ backups
```

`sync` is the one-shot version of `watch`: it merges every `.jwlibrary` in the
folder, skips its own previous output, writes a timestamped merged file, and
records what it did in `.jwsync-state.json`. Run it again after nothing has
changed and it tells you so instead of writing another copy.

### Check that a merge lost nothing

`watch` and the web interface do this automatically after every merge. To run it
yourself:

```bash
jwsync verify merged.jwlibrary phone.jwlibrary tablet.jwlibrary
```

It walks every note, highlight, bookmark, tag, study answer, media file and
playlist item in each source and asserts it is findable in the merged file, then
exits non-zero if anything is not.

```
items checked and found in the merged file
  Bookmark                                2
  IndependentMedia                       81
  Note                                   33
  PlaylistItem                           78
  UserMark                             4924
  ...
PASS -- every item from every source is present
```

## How the merge decides things

Every table is keyed on the identity JW Library itself uses, so the same note or
highlight seen from two devices collapses into one row instead of being
duplicated. **Merging is idempotent**: running it again over the same inputs adds
nothing.

| Data | Matched on | When both sides differ |
| --- | --- | --- |
| Notes | `Guid` | The copy with the newer `LastModified` wins; the other is reported |
| Highlights (`UserMark`) | `UserMarkGuid` | Higher `Version` wins, and its block ranges replace the older set |
| Highlight ranges | Their extent within a highlight | Union, never duplicated |
| Locations | Full natural key, then the two `UNIQUE` constraints | Mapped onto the existing location |
| Tags | `(Type, Name)` | Same name, different type stays separate |
| Tag membership | Tag plus the note, location or playlist item | Appended at a free `Position` |
| Bookmarks | Publication, location and block | A new bookmark takes the first free slot; past slot 9 it is reported, not silently dropped |
| Study answers (`InputField`) | Location plus field tag | No timestamp exists, so `--input-fields` decides: `keep` (default) or `overwrite` |
| Media | Content hash | Identical files are shared; different files that happen to share a name are renamed |
| Playlist items | Content, plus the playlist they belong to | The same song in two playlists stays two items, as JW Library models it |

Every merge ends with a `PRAGMA foreign_key_check`. If it finds anything, the
report says so and the command exits non-zero.

### Options

| Flag | Effect |
| --- | --- |
| `--input-fields keep\|overwrite` | How to resolve study answers that differ (default `keep`) |
| `--device-name NAME` | `deviceName` recorded in the merged manifest |
| `--hash-mode sha256\|keep\|empty` | What goes into `manifest.userDataBackup.hash` (default `sha256`) |
| `--json` | Emit the report as JSON |
| `--report FILE` | Also write the JSON report to a file |
| `--force` | Overwrite the output / re-merge even if nothing changed |
| `--interval N` | Seconds between polls in `watch` (default 30) |
| `--once` | Check once and exit, for cron or Task Scheduler |
| `--fresh` | Rebuild from the device backups alone, ignoring the previous merge |
| `--no-history` | Do not keep dated copies of merges |
| `--with-local` | Also export this computer's own library before each merge |
| `--push-local` | Also install the merged result back into this computer's library |
| `--library PATH` | The JW Library data folder, if it is not found automatically |
| `--no-integrity-check` | Skip the foreign-key verification pass |

## The file format

A `.jwlibrary` file is a ZIP archive holding `userData.db` (SQLite), a
`manifest.json`, and the media blobs referenced by playlists.

Two details that matter and are not obvious:

- **`IndependentMedia.Hash` is a SHA-256 with a formatting quirk.** JW Library
  renders each byte with a `%x`-style format instead of `%02x`, so bytes below
  `0x10` lose their leading zero and the string is usually shorter than 64
  characters. `jwsync` reproduces that encoding exactly (`archive.jw_hex`), which
  is what lets it recognise the same media file exported from two devices.
- **`manifest.userDataBackup.hash` cannot be reproduced.** It is not a hash of
  the exported database file — the database is re-serialised on export, so no
  file hash would be stable. `jwsync` regenerates it in the same `jw_hex`
  encoding. If a device ever refuses a merged file, `--hash-mode keep` reuses the
  base backup's original value and `--hash-mode empty` writes an empty string.

On a desktop the app keeps that database in **WAL mode**, and the main file can
be almost empty while the write-ahead log holds nearly everything — so reading
it means folding the log in (`jwsync` uses `VACUUM INTO`, which is consistent
even while the app is running), and writing it means deleting the stale log so
it cannot be replayed over the new database. `jwsync push` does both, and
refuses outright while JW Library is open.

`jwsync` refuses to merge backups whose `schemaVersion` differs; update JW
Library on both devices and export again. Schema versions 14–16 are recognised;
anything else merges with a warning.

## Limitations

- Additive only, so deletions do not propagate (see the first section). Use
  `--fresh` to rebuild from the device backups alone when you want dropped data
  to stay dropped.
- On phones and tablets, export and restore cannot be automated; JW Library
  exposes no interface for them and the app's storage is not reachable from a
  computer. On a Mac or PC, `pull` and `push` remove even those steps.
- Bookmarks are capped at 10 slots per publication by the schema; extras are
  reported rather than merged.
- Study answers carry no timestamp, so their conflicts are resolved by policy,
  not by recency.
- Playlist items have no stable identifier in the schema, so they are matched on
  content — an item whose label and trim points were edited on one device is
  treated as a new item.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest      # 106 tests
.venv/bin/ruff check src tests
```

The suite runs on Python 3.9 through 3.13. The browser-parity tests need Node
and skip themselves without it. It builds `.jwlibrary` archives from the schema in
`tests/fixtures/schema_v16.sql`, so it carries no personal study data. `*.jwlibrary`
is in `.gitignore` for the same reason — do not commit your own backups.

## License

MIT. See [LICENSE](LICENSE).
