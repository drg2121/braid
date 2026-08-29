"""Command line interface for braid."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from . import __version__
from .archive import (
    SUPPORTED_SCHEMA_VERSIONS,
    ArchiveError,
    Backup,
    sha256_file,
    unique_path,
    write_backup,
)
from .local import (
    LocalLibrary,
    LocalLibraryError,
    default_device_name,
    find_libraries,
    find_library,
)
from .merge import COUNTED_TABLES, MergeError, MergeOptions, merge_backups
from .report import MergeReport
from .verify import verify
from .watch import STABLE_OUTPUT_NAME, watch

STATE_FILENAME = ".braid-state.json"


# -- helpers ---------------------------------------------------------------


def _open_all(paths: list[Path], stack: list[Backup]) -> list[Backup]:
    backups = []
    for path in paths:
        backup = Backup.open(path)
        stack.append(backup)
        if backup.manifest.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            print(
                f"warning: {path.name} uses schema version "
                f"{backup.manifest.schema_version}, which braid has not been "
                f"validated against (known: "
                f"{sorted(SUPPORTED_SCHEMA_VERSIONS)})",
                file=sys.stderr,
            )
        backups.append(backup)
    return backups


def _pick_base(backups: list[Backup]) -> tuple[Backup, list[Backup]]:
    """The most recently modified backup becomes the base."""
    ordered = sorted(backups, key=lambda b: b.sort_key(), reverse=True)
    return ordered[0], ordered[1:]


def _default_output(paths: list[Path]) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    return paths[0].parent / f"UserdataBackup_{stamp}_merged.jwlibrary"


def _discover(folder: Path, exclude: set[Path]) -> list[Path]:
    return sorted(
        p
        for p in folder.glob("*.jwlibrary")
        if p.resolve() not in exclude and not p.name.startswith(".")
    )


# -- commands ---------------------------------------------------------------


def cmd_inspect(args: argparse.Namespace) -> int:
    payload = []
    for path in args.files:
        with Backup.open(path) as backup:
            conn = backup.connect()
            counts = {}
            for table in COUNTED_TABLES:
                try:
                    counts[table] = conn.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                except Exception:
                    pass
            conn.close()
            media = sum(1 for _ in backup.media_files())
            entry = {
                "file": str(path),
                "device": backup.manifest.device_name,
                "schemaVersion": backup.manifest.schema_version,
                "created": backup.manifest.creation_date,
                "lastModified": backup.manifest.last_modified_date,
                "mediaFiles": media,
                "counts": counts,
            }
            payload.append(entry)

            if not args.json:
                print(f"{path.name}")
                print(f"  device        {entry['device']}")
                print(f"  schema        v{entry['schemaVersion']}")
                print(f"  created       {entry['created']}")
                print(f"  lastModified  {entry['lastModified']}")
                print(f"  media files   {media}")
                for table, n in counts.items():
                    if n:
                        print(f"    {table:<34}{n:>7}")
                print()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _run_merge(
    paths: list[Path],
    output: Path,
    options: MergeOptions,
    hash_mode: str,
    device_name: str,
) -> MergeReport:
    stack: list[Backup] = []
    try:
        backups = _open_all(paths, stack)
        base, sources = _pick_base(backups)
        with tempfile.TemporaryDirectory(prefix="braid-out-") as tmp:
            db_path, media, report = merge_backups(base, sources, Path(tmp), options)
            manifest = base.manifest
            manifest.device_name = device_name or f"{base.manifest.device_name} (merged)"
            write_backup(
                output,
                db_path,
                media.members,
                manifest,
                hash_mode=hash_mode,
            )
            report.output = str(output)
        return report
    finally:
        for backup in stack:
            backup.close()


def cmd_merge(args: argparse.Namespace) -> int:
    if len(args.files) < 2:
        print("merge needs at least two backups", file=sys.stderr)
        return 2

    output = Path(args.output) if args.output else _default_output(args.files)
    if output.exists() and not args.force:
        print(
            f"{output} already exists; pass --force to overwrite", file=sys.stderr
        )
        return 1

    options = MergeOptions(
        input_fields=args.input_fields, check_integrity=not args.no_integrity_check
    )
    try:
        report = _run_merge(
            args.files, output, options, args.hash_mode, args.device_name
        )
    except (ArchiveError, MergeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(report.to_json() if args.json else report.to_text())
    if args.report:
        Path(args.report).write_text(report.to_json(), encoding="utf-8")
    return 1 if report.integrity_errors else 0


def cmd_sync(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"{folder} is not a directory", file=sys.stderr)
        return 2

    state_path = folder / STATE_FILENAME
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {"runs": []}
    )

    previous = {Path(r["output"]).resolve() for r in state["runs"] if r.get("output")}
    inputs = _discover(folder, previous)
    if len(inputs) < 2:
        print(
            f"found {len(inputs)} backup(s) in {folder}; need at least two to sync",
            file=sys.stderr,
        )
        return 1

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    output = unique_path(folder / f"UserdataBackup_{stamp}_merged.jwlibrary")
    options = MergeOptions(
        input_fields=args.input_fields, check_integrity=not args.no_integrity_check
    )

    fingerprints = {p.name: sha256_file(p) for p in inputs}
    last = state["runs"][-1] if state["runs"] else None
    if (
        last
        and last.get("inputs") == fingerprints
        and Path(last.get("output", "")).exists()
        and not args.force
    ):
        print(
            "nothing changed since the last sync; "
            f"current merge is {last['output']}"
        )
        return 0

    try:
        report = _run_merge(inputs, output, options, args.hash_mode, args.device_name)
    except (ArchiveError, MergeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    state["runs"].append(
        {
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "inputs": fingerprints,
            "output": str(output),
            "report": report.to_dict(),
        }
    )
    state["runs"] = state["runs"][-20:]
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(report.to_json() if args.json else report.to_text())
    print()
    print("Restore this file on every device:")
    print(f"  {output}")
    return 1 if report.integrity_errors else 0


def cmd_verify(args: argparse.Namespace) -> int:
    result = verify(args.merged, args.sources)
    print(json.dumps(result.to_dict(), indent=2) if args.json else result.to_text())
    return 0 if result.ok else 1


def _library(args: argparse.Namespace) -> LocalLibrary:
    if getattr(args, "library", None):
        library = LocalLibrary(Path(args.library).expanduser().resolve())
        if not library.exists():
            raise LocalLibraryError(f"no userData.db in {library.path}")
        return library
    return find_library()


def cmd_status(args: argparse.Namespace) -> int:
    found = find_libraries()
    if not found:
        print("No JW Library installation found on this computer.")
        print(
            "That is normal on Linux, and on a Mac or PC where the app is not "
            "installed. Phones and tablets always export by hand."
        )
        return 1

    for library in found:
        print(f"JW Library data folder : {library.path}")
        print(f"  schema version       : v{library.schema_version()}")
        print(f"  app running          : {'yes' if library.is_running() else 'no'}")
        counts = library.counts()
        for table, n in counts.items():
            if n:
                print(f"    {table:<34}{n:>7}")
        print()
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    library = _library(args)
    folder = Path(args.folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    name = args.device_name or default_device_name()
    out = folder / f"UserdataBackup_{name}_local.jwlibrary"

    library.export(out, device_name=name)
    print(f"Exported this computer's library to {out}")
    print("Safe to run while JW Library is open.")
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    library = _library(args)
    source = Path(args.backup).expanduser()
    if not source.is_file():
        print(f"{source} does not exist", file=sys.stderr)
        return 2

    if library.is_running():
        print(
            "JW Library is running. Quit it completely, then run this again -- "
            "writing to its database while it is open risks corrupting it.",
            file=sys.stderr,
        )
        return 1

    check = verify(source, [source])
    if not check.ok:
        print(f"{source.name} does not verify against itself; refusing", file=sys.stderr)
        return 1

    if not args.yes:
        print("About to replace this computer's JW Library with:")
        print(f"  {source}")
        print()
        print("The current library will be copied aside first, but this replaces")
        print("what JW Library shows on this computer. Re-run with --yes to do it.")
        return 1

    result = library.install(source)
    print(f"Installed {source.name} into {library.path}")
    print(f"  previous library saved to {result['safetyCopy']}")
    print(f"  media files added         {result['mediaCopied']}")
    for table in sorted(result["after"]):
        before = result["before"].get(table, 0)
        after = result["after"][table]
        if after != before:
            print(f"  {table:<34}{before:>7} -> {after:>7}")
    return 0


def cmd_install_agent(args: argparse.Namespace) -> int:
    from .agent import install

    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print(f"{folder} is not a directory", file=sys.stderr)
        return 2

    info = install(folder, args.interval)
    print(f"Service definition for {info['system']}")
    if info["path"]:
        print(f"  written to  {info['path']}")
    print()
    print("It is not running yet. Start it with:")
    print(f"  {info['activate']}")
    print()
    print("To stop it later:")
    print(f"  {info['deactivate']}")
    print(f"Logs: {info['logs']}")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print(f"{folder} is not a directory", file=sys.stderr)
        return 2
    options = MergeOptions(
        input_fields=args.input_fields, check_integrity=not args.no_integrity_check
    )
    library = None
    if args.with_local or args.push_local:
        try:
            library = _library(args)
        except LocalLibraryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    return watch(
        folder,
        interval=args.interval,
        options=options,
        accumulate=not args.fresh,
        keep_history=not args.no_history,
        once=args.once,
        library=library,
        push_local=args.push_local,
    )


def cmd_serve(args: argparse.Namespace) -> int:
    from .webui import serve

    serve(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


# -- argument parsing --------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="braid",
        description=(
            "Merge JW Library backups from several devices into one, so notes, "
            "highlights, bookmarks, tags and playlists survive on all of them."
        ),
    )
    parser.add_argument("--version", action="version", version=f"braid {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_merge_options(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--input-fields",
            choices=("keep", "overwrite"),
            default="keep",
            help=(
                "how to resolve study-question answers that differ between "
                "devices; the schema stores no timestamp for them "
                "(default: keep the newest backup's own value)"
            ),
        )
        p.add_argument(
            "--hash-mode",
            choices=("sha256", "keep", "empty"),
            default="sha256",
            help="what to write into manifest.userDataBackup.hash (default: sha256)",
        )
        p.add_argument(
            "--device-name",
            default="",
            help="deviceName recorded in the merged manifest",
        )
        p.add_argument(
            "--no-integrity-check",
            action="store_true",
            help="skip the foreign-key verification pass",
        )
        p.add_argument("--json", action="store_true", help="print the report as JSON")

    p_inspect = sub.add_parser(
        "inspect", help="show what a backup contains without changing anything"
    )
    p_inspect.add_argument("files", nargs="+", type=Path)
    p_inspect.add_argument("--json", action="store_true")
    p_inspect.set_defaults(func=cmd_inspect)

    p_merge = sub.add_parser("merge", help="merge two or more backups into a new one")
    p_merge.add_argument("files", nargs="+", type=Path)
    p_merge.add_argument("-o", "--output", type=Path)
    p_merge.add_argument("--force", action="store_true", help="overwrite the output")
    p_merge.add_argument("--report", type=Path, help="also write the report as JSON here")
    add_merge_options(p_merge)
    p_merge.set_defaults(func=cmd_merge)

    p_sync = sub.add_parser(
        "sync",
        help=(
            "merge every .jwlibrary in a folder (a shared Drive/iCloud folder "
            "works well) and remember what was already merged"
        ),
    )
    p_sync.add_argument("folder", type=Path)
    p_sync.add_argument(
        "--force", action="store_true", help="merge again even if nothing changed"
    )
    add_merge_options(p_sync)
    p_sync.set_defaults(func=cmd_sync)

    p_verify = sub.add_parser(
        "verify",
        help=(
            "check that a merged backup still contains every note, highlight, "
            "bookmark, tag, study answer, media file and playlist item from the "
            "backups it was built from"
        ),
    )
    p_verify.add_argument("merged", type=Path)
    p_verify.add_argument(
        "sources", nargs="+", type=Path, help="the backups that went into the merge"
    )
    p_verify.add_argument("--json", action="store_true")
    p_verify.set_defaults(func=cmd_verify)

    def add_library_option(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--library",
            type=Path,
            help="path to the JW Library data folder, if it is not found automatically",
        )

    p_status = sub.add_parser(
        "status", help="show the JW Library installed on this computer, if any"
    )
    p_status.set_defaults(func=cmd_status)

    p_pull = sub.add_parser(
        "pull",
        help=(
            "export this computer's live JW Library into the shared folder, "
            "with no Create Backup tapping needed"
        ),
    )
    p_pull.add_argument("folder", type=Path)
    p_pull.add_argument("--device-name", default="")
    add_library_option(p_pull)
    p_pull.set_defaults(func=cmd_pull)

    p_push = sub.add_parser(
        "push",
        help=(
            "install a merged backup straight into this computer's JW Library, "
            "with no Restore Backup tapping needed (JW Library must be closed)"
        ),
    )
    p_push.add_argument("backup", type=Path)
    p_push.add_argument(
        "--yes", action="store_true", help="confirm replacing the local library"
    )
    add_library_option(p_push)
    p_push.set_defaults(func=cmd_push)

    p_watch = sub.add_parser(
        "watch",
        help=(
            "keep merging automatically: watch a shared folder and rebuild "
            f"{STABLE_OUTPUT_NAME!r} whenever any device drops a new backup in"
        ),
    )
    p_watch.add_argument("folder", type=Path)
    p_watch.add_argument(
        "--interval", type=float, default=30.0, help="seconds between polls"
    )
    p_watch.add_argument(
        "--once", action="store_true", help="check once and exit, for scheduled runs"
    )
    p_watch.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "rebuild from the device backups alone instead of folding in the "
            "previous merged result"
        ),
    )
    p_watch.add_argument(
        "--no-history", action="store_true", help="do not keep dated copies of merges"
    )
    p_watch.add_argument(
        "--with-local",
        action="store_true",
        help=(
            "also export this computer's own JW Library into the folder before "
            "each merge; safe while the app is open"
        ),
    )
    p_watch.add_argument(
        "--push-local",
        action="store_true",
        help=(
            "also install the merged result back into this computer's JW "
            "Library after each merge; skipped while the app is open"
        ),
    )
    add_library_option(p_watch)
    add_merge_options(p_watch)
    p_watch.set_defaults(func=cmd_watch)

    p_agent = sub.add_parser(
        "install-agent",
        help="write a launchd/systemd/Task Scheduler definition so watch runs at login",
    )
    p_agent.add_argument("folder", type=Path)
    p_agent.add_argument("--interval", type=int, default=30)
    p_agent.set_defaults(func=cmd_install_agent)

    p_serve = sub.add_parser("serve", help="open the local drag-and-drop web interface")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--no-browser", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ArchiveError, LocalLibraryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
