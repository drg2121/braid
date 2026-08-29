"""Watch a folder and merge automatically whenever a backup changes.

JW Library exposes no API, no URL scheme and no Shortcuts actions, so exporting
a backup and restoring one will always be taps inside the app. Everything
between those two ends can be automated, and this is that middle: point the
watcher at a folder your devices already sync (iCloud Drive, Google Drive,
Dropbox), and a merged file appears there under a stable name as soon as any
device drops a new backup in.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .archive import Backup, write_backup
from .merge import MergeOptions, merge_backups
from .report import MergeReport
from .verify import VerifyResult, verify

#: Name of the merged file. It never changes, so the file you restore on each
#: device is always the same one and the cloud provider simply updates it.
STABLE_OUTPUT_NAME = "JW Library MERGED.jwlibrary"

#: Where dated copies of previous merges and the watcher's state are kept.
HISTORY_DIRNAME = "_jwsync_history"

STATE_FILENAME = "watch-state.json"


@dataclass(frozen=True)
class FileState:
    name: str
    size: int
    mtime: float


def snapshot(folder: Path, exclude: set[str]) -> frozenset[FileState]:
    """A cheap fingerprint of the folder, used to notice changes."""
    out = set()
    for path in folder.glob("*.jwlibrary"):
        if path.name in exclude or path.name.startswith("."):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        out.add(FileState(path.name, stat.st_size, stat.st_mtime))
    return frozenset(out)


def pending_downloads(folder: Path) -> list[str]:
    """iCloud placeholders for files that have not been downloaded yet."""
    return sorted(
        p.name[1:-7]  # strip the leading dot and the .icloud suffix
        for p in folder.glob(".*.jwlibrary.icloud")
    )


def _state_path(folder: Path) -> Path:
    return folder / HISTORY_DIRNAME / STATE_FILENAME


def read_state(folder: Path) -> frozenset[FileState] | None:
    """The folder fingerprint as of the last successful merge, if any."""
    path = _state_path(folder)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return frozenset(
            FileState(e["name"], int(e["size"]), float(e["mtime"]))
            for e in raw.get("merged", [])
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_state(folder: Path, state: frozenset[FileState]) -> None:
    path = _state_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "merged": [
                    {"name": f.name, "size": f.size, "mtime": f.mtime}
                    for f in sorted(state, key=lambda f: f.name)
                ],
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def inputs_for(folder: Path, *, accumulate: bool) -> list[Path]:
    """The backups to merge, newest first is decided later by the merge itself."""
    stable = folder / STABLE_OUTPUT_NAME
    paths = [
        p
        for p in sorted(folder.glob("*.jwlibrary"))
        if not p.name.startswith(".") and p.name != STABLE_OUTPUT_NAME
    ]
    if accumulate and stable.is_file():
        paths.append(stable)
    return paths


def merge_folder(
    folder: Path,
    *,
    options: MergeOptions | None = None,
    accumulate: bool = True,
    keep_history: bool = True,
) -> tuple[Path, MergeReport, VerifyResult]:
    """Merge everything in ``folder`` into the stable output, then verify it."""
    paths = inputs_for(folder, accumulate=accumulate)
    if len(paths) < 2:
        raise ValueError(
            f"found {len(paths)} backup(s) in {folder}; need at least two to merge"
        )

    stack = [Backup.open(p) for p in paths]
    try:
        # The previous merged file is by construction a superset of everything
        # merged so far, so it makes the correct base: the work already done is
        # not repeated, and the report counts only genuinely new rows.
        stable = next(
            (b for b in stack if b.path.name == STABLE_OUTPUT_NAME), None
        )
        if stable is not None:
            base = stable
            sources = [b for b in stack if b is not stable]
            sources.sort(key=lambda b: b.sort_key(), reverse=True)
        else:
            ordered = sorted(stack, key=lambda b: b.sort_key(), reverse=True)
            base, sources = ordered[0], ordered[1:]

        import tempfile

        with tempfile.TemporaryDirectory(prefix="jwsync-watch-") as tmp:
            db_path, media, report = merge_backups(base, sources, Path(tmp), options)
            manifest = base.manifest
            manifest.device_name = "jwsync merged"
            output = folder / STABLE_OUTPUT_NAME
            # write_backup writes to a .part file and renames, so a device
            # syncing the folder never sees a half-written archive.
            write_backup(output, db_path, media.members, manifest)
            report.output = str(output)
    finally:
        for backup in stack:
            backup.close()

    if keep_history:
        history = folder / HISTORY_DIRNAME
        history.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        (history / f"merged-{stamp}.jwlibrary").write_bytes(output.read_bytes())

    checked = verify(output, [p for p in paths if p.name != STABLE_OUTPUT_NAME])
    return output, report, checked


def watch(
    folder: Path,
    *,
    interval: float = 30.0,
    options: MergeOptions | None = None,
    accumulate: bool = True,
    keep_history: bool = True,
    once: bool = False,
    log: Callable[[str], None] = print,
) -> int:
    """Poll ``folder`` and merge whenever the set of backups changes.

    Polling rather than filesystem events is deliberate: cloud-synced folders
    often materialise files without emitting the events a watcher would rely
    on, and a file that is still downloading must be allowed to finish. So a
    change has to look identical on two consecutive polls before it triggers a
    merge -- except under ``once``, where a single scheduled check is the whole
    run and the file is expected to have settled already.

    What has been merged is remembered in the folder, so restarting the watcher
    or running it from cron does not redo finished work.
    """
    folder = Path(folder)
    exclude = {STABLE_OUTPUT_NAME}

    merged_for: frozenset[FileState] | None = None
    if (folder / STABLE_OUTPUT_NAME).is_file():
        merged_for = read_state(folder)
    candidate: frozenset[FileState] | None = None

    def stamp() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def do_merge(current: frozenset[FileState]) -> bool:
        if len(inputs_for(folder, accumulate=accumulate)) < 2:
            log(f"[{stamp()}] only one backup here so far, nothing to merge yet")
            return False
        try:
            output, report, checked = merge_folder(
                folder,
                options=options,
                accumulate=accumulate,
                keep_history=keep_history,
            )
        except Exception as exc:
            log(f"[{stamp()}] merge failed: {exc}")
            return False

        added = sum(sum(sr.added.values()) for sr in report.sources)
        verdict = "verified" if checked.ok else "CHECK FAILED"
        log(
            f"[{stamp()}] merged {len(report.sources) + 1} backups, "
            f"{added} new rows, {verdict} -> {output.name}"
        )
        for miss in checked.missing[:10]:
            log(f"           missing {miss.table}: {miss.description}")
        for err in report.integrity_errors:
            log(f"           integrity: {err}")
        write_state(folder, current)
        return True

    if not once:
        log(f"[{stamp()}] watching {folder} every {interval:g}s (Ctrl-C to stop)")

    while True:
        waiting = pending_downloads(folder)
        if waiting:
            log(f"[{stamp()}] waiting for the cloud to download: {', '.join(waiting)}")

        current = snapshot(folder, exclude)

        if current == merged_for:
            if once:
                log(f"[{stamp()}] up to date, nothing to do")
                return 0
        elif once or current == candidate:
            if do_merge(current):
                merged_for = current
            candidate = None
            if once:
                return 0
        else:
            candidate = current
            log(f"[{stamp()}] change detected, letting it settle")

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            log(f"[{stamp()}] stopped")
            return 0


__all__ = [
    "HISTORY_DIRNAME",
    "STABLE_OUTPUT_NAME",
    "STATE_FILENAME",
    "FileState",
    "inputs_for",
    "merge_folder",
    "pending_downloads",
    "read_state",
    "snapshot",
    "watch",
    "write_state",
]
