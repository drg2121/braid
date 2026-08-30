"""The browser must read a write-ahead log the way SQLite does.

This matters more than it looks. JW Library keeps its database in WAL mode, and
on a real device userData.db can be a 4 KB empty shell while every note and
highlight lives in the log beside it. Reading only the database yields a
library with no tables -- which, restored, would wipe someone's real one.

So these tests build databases whose contents exist only in the log, hand the
pair to the browser's applyWal, and check the result against what SQLite
itself recovers. They also make sure a damaged log is refused rather than
half-applied.

Skipped when Node is not installed; CI has it.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import struct
import subprocess
import tempfile
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node is not installed")

# Each call pays for a fresh Node start and a WebAssembly compile before it
# does any work. That is milliseconds on a developer's machine and minutes on a
# starved shared runner, so the ceiling is set for the worst case rather than
# the usual one -- a genuine hang still fails, just later.
NODE_TIMEOUT = 900

RUNNER = r"""
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const web = process.argv[2];
const dir = process.argv[3];
const webUrl = pathToFileURL(web + "/").href;
const require = createRequire(webUrl);
const initSqlJs = require(web + "/vendor/sql-wasm.js");
const { applyWal } = await import(webUrl + "wal.js");

const db = new Uint8Array(readFileSync(dir + "/test.db"));
const walPath = dir + "/test.db-wal";
const wal = existsSync(walPath) ? new Uint8Array(readFileSync(walPath)) : null;

let out;
let error = null;
try {
  out = applyWal(db, wal);
} catch (e) {
  error = e.message;
  out = db;
}

const SQL = await initSqlJs({ locateFile: () => web + "/vendor/sql-wasm.wasm" });
let rows = null;
let readError = null;
try {
  const d = new SQL.Database(out);
  const stmt = d.prepare("SELECT id, label FROM things ORDER BY id");
  rows = [];
  while (stmt.step()) rows.push(stmt.getAsObject());
  stmt.free();
  d.close();
} catch (e) {
  readError = e.message;
}

console.log(JSON.stringify({
  dbBytes: db.length,
  walBytes: wal ? wal.length : 0,
  appliedBytes: out.length,
  error,
  readError,
  rows,
}));
"""


def run_apply_wal(folder: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        runner = Path(tmp) / "runner.mjs"
        runner.write_text(RUNNER, encoding="utf-8")
        result = subprocess.run(
            [NODE, str(runner), str(WEB), str(folder)],
            capture_output=True,
            text=True,
            timeout=NODE_TIMEOUT,
            env=dict(os.environ),
        )
    if result.returncode != 0:
        pytest.fail(f"applyWal crashed:\n{result.stderr[-2000:]}")
    line = [ln for ln in result.stdout.splitlines() if ln.startswith("{")]
    if not line:
        pytest.fail(f"no result:\n{result.stdout[-2000:]}")
    return json.loads(line[-1])


def build_wal_database(folder: Path, labels: list[str]) -> Path:
    """A database whose rows live only in its write-ahead log.

    SQLite checkpoints when the last connection closes, which would fold the
    log away and defeat the point. So the pair is copied out while a connection
    is still open -- leaving the target folder in exactly the shape JW Library
    leaves on a device: a nearly empty database beside a log holding everything.
    """
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as staging:
        source = Path(staging) / "test.db"
        conn = sqlite3.connect(source)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA wal_autocheckpoint = 0")
            conn.execute("CREATE TABLE things (id INTEGER PRIMARY KEY, label TEXT)")
            for n, label in enumerate(labels, start=1):
                conn.execute("INSERT INTO things (id, label) VALUES (?, ?)", (n, label))
            conn.commit()
            for suffix in ("", "-wal"):
                sidecar = source.with_name(source.name + suffix)
                if sidecar.is_file():
                    shutil.copy(sidecar, folder / sidecar.name)
        finally:
            conn.close()
    return folder / "test.db"


def sqlite_rows(path: Path) -> list[dict]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [
            {"id": r[0], "label": r[1]}
            for r in conn.execute("SELECT id, label FROM things ORDER BY id")
        ]
    finally:
        conn.close()


# -- the happy path ---------------------------------------------------------


def test_rows_that_exist_only_in_the_log_are_recovered(tmp_path):
    folder = tmp_path / "lib"
    build_wal_database(folder, ["first", "second", "third"])

    wal = folder / "test.db-wal"
    assert wal.is_file() and wal.stat().st_size > 0, "the fixture needs a real log"

    result = run_apply_wal(folder)
    assert result["error"] is None
    assert result["readError"] is None
    assert [r["label"] for r in result["rows"]] == ["first", "second", "third"]
    assert result["appliedBytes"] > result["dbBytes"] or result["walBytes"] > 0


def test_the_result_matches_what_sqlite_recovers(tmp_path):
    folder = tmp_path / "lib"
    build_wal_database(folder, [f"row {n}" for n in range(1, 40)])

    from_js = run_apply_wal(folder)
    # Read with SQLite only afterwards: opening the pair checkpoints it.
    from_sqlite = sqlite_rows(folder / "test.db")

    assert from_js["rows"] == from_sqlite


def test_the_main_file_alone_is_not_enough(tmp_path):
    """The failure this whole module exists to prevent."""
    folder = tmp_path / "lib"
    build_wal_database(folder, ["only in the log"])

    alone = tmp_path / "alone"
    alone.mkdir()
    shutil.copy(folder / "test.db", alone / "test.db")  # no -wal beside it

    result = run_apply_wal(alone)
    assert result["rows"] is None, "reading the database alone should find no table"
    assert result["readError"] is not None


# -- damaged and unusual logs ----------------------------------------------


def test_a_missing_log_leaves_the_database_alone(tmp_path):
    folder = tmp_path / "lib"
    path = folder / "test.db"
    folder.mkdir()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE things (id INTEGER PRIMARY KEY, label TEXT)")
    conn.execute("INSERT INTO things VALUES (1, 'already in the database')")
    conn.commit()
    conn.close()

    result = run_apply_wal(folder)
    assert result["walBytes"] == 0
    assert [r["label"] for r in result["rows"]] == ["already in the database"]


def test_a_file_that_is_not_a_log_is_refused(tmp_path):
    folder = tmp_path / "lib"
    build_wal_database(folder, ["kept"])
    (folder / "test.db-wal").write_bytes(b"this is not a write-ahead log at all" * 40)

    result = run_apply_wal(folder)
    assert result["error"] is not None
    assert "write-ahead log" in result["error"]


def test_an_empty_log_changes_nothing(tmp_path):
    folder = tmp_path / "lib"
    build_wal_database(folder, ["kept"])
    (folder / "test.db-wal").write_bytes(b"")

    result = run_apply_wal(folder)
    assert result["error"] is None
    assert result["appliedBytes"] == result["dbBytes"]


def test_a_torn_frame_stops_the_replay(tmp_path):
    """A half-written frame must be discarded, not applied."""
    folder = tmp_path / "lib"
    build_wal_database(folder, ["first", "second", "third"])
    wal_path = folder / "test.db-wal"
    data = bytearray(wal_path.read_bytes())

    page_size = struct.unpack(">I", data[8:12])[0]
    frame_size = 24 + page_size
    assert len(data) >= 32 + frame_size, "the fixture needs at least one frame"

    # Corrupt the first frame's page content, leaving its checksum stale.
    first_page = 32 + 24
    data[first_page] ^= 0xFF
    wal_path.write_bytes(bytes(data))

    result = run_apply_wal(folder)
    assert result["error"] is None
    # Nothing from the log was applied, so the tables are not there.
    assert result["rows"] is None or result["rows"] == []


def test_frames_from_an_earlier_generation_are_ignored(tmp_path):
    folder = tmp_path / "lib"
    build_wal_database(folder, ["first", "second"])
    wal_path = folder / "test.db-wal"
    data = bytearray(wal_path.read_bytes())

    # Change the first frame's salt so it no longer belongs to this log.
    struct.pack_into(">I", data, 32 + 8, 0xDEADBEEF)
    wal_path.write_bytes(bytes(data))

    result = run_apply_wal(folder)
    assert result["error"] is None
    assert result["rows"] is None or result["rows"] == []


def test_an_impossible_page_size_is_refused(tmp_path):
    folder = tmp_path / "lib"
    build_wal_database(folder, ["kept"])
    wal_path = folder / "test.db-wal"
    data = bytearray(wal_path.read_bytes())
    struct.pack_into(">I", data, 8, 12345)  # not a power of two
    wal_path.write_bytes(bytes(data))

    result = run_apply_wal(folder)
    assert result["error"] is not None
    assert "page size" in result["error"]


def test_uncommitted_frames_are_not_applied(tmp_path):
    """Frames written after the last commit belong to a transaction that never
    finished, and must be left out."""
    folder = tmp_path / "lib"
    build_wal_database(folder, ["committed"])
    wal_path = folder / "test.db-wal"
    data = bytearray(wal_path.read_bytes())

    page_size = struct.unpack(">I", data[8:12])[0]
    frame_size = 24 + page_size

    # Clear every commit marker; with no commit at all, nothing may be applied.
    at = 32
    while at + frame_size <= len(data):
        struct.pack_into(">I", data, at + 4, 0)
        at += frame_size
    wal_path.write_bytes(bytes(data))

    result = run_apply_wal(folder)
    assert result["error"] is None
    assert result["appliedBytes"] == result["dbBytes"], (
        "with no commit in the log, the database must be returned untouched"
    )
