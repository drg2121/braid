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

## Install

Python 3.10 or newer. No third-party dependencies.

```bash
pip install -e .
```

Or run it straight from a checkout without installing:

```bash
python -m jwsync --help
```

## Use it

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

### Sync a shared folder

The workflow that actually keeps three devices in step: point every device's
backup export at one folder that iCloud Drive, Google Drive or Dropbox already
syncs, then run:

```bash
jwsync sync ~/Library/Mobile\ Documents/com~apple~CloudDocs/JW\ backups
```

`sync` merges every `.jwlibrary` in the folder, skips its own previous output,
writes a timestamped merged file, and records what it did in
`.jwsync-state.json`. Run it again after nothing has changed and it tells you so
instead of writing another copy.

The routine, once per round of changes:

1. On each device: **Personal Study ▸ ⤒ ▸ Create Backup**, save into the shared folder.
2. On the laptop: `jwsync sync <folder>`.
3. On each device: **Personal Study ▸ ⤒ ▸ Restore Backup**, pick the merged file.

### Local web interface

```bash
jwsync serve
```

Opens `http://127.0.0.1:8765` — point it at a folder, tick the backups you want,
merge. It binds to localhost only and works on folder paths rather than uploads,
because real libraries run to hundreds of megabytes.

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

`jwsync` refuses to merge backups whose `schemaVersion` differs; update JW
Library on both devices and export again. Schema versions 14–16 are recognised;
anything else merges with a warning.

## Limitations

- Additive only, so deletions do not propagate (see the first section).
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
.venv/bin/python -m pytest      # 48 tests
.venv/bin/ruff check src tests
```

The test suite builds `.jwlibrary` archives from the schema in
`tests/fixtures/schema_v16.sql`, so it carries no personal study data. `*.jwlibrary`
is in `.gitignore` for the same reason — do not commit your own backups.

## License

MIT. See [LICENSE](LICENSE).
