"""The browser engine and the Python engine must agree.

There are two implementations of the same merge -- Python for the desktop, and
JavaScript so a phone or tablet can do it with no computer involved. Two
implementations drift. These tests merge the same libraries with both and fail
if the results differ, which is the only thing that keeps them honest.

Skipped when Node is not installed; CI has it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from jwsync.archive import Backup, write_backup
from jwsync.merge import merge_backups
from jwsync.verify import verify

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node is not installed")

NEWER = "2026-08-01T00:00:00+0000"
OLDER = "2026-01-01T00:00:00+0000"

RUNNER = r"""
import { openAsBlob } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(process.argv[2] + "/");
const initSqlJs = require(process.argv[2] + "/vendor/sql-wasm.js");
const { BackupFile } = await import(process.argv[2] + "/jwlibrary.js");
const { mergeInto, countsOf } = await import(process.argv[2] + "/merge.js");
const { verify } = await import(process.argv[2] + "/verify.js");

const SQL = await initSqlJs({
  locateFile: () => process.argv[2] + "/vendor/sql-wasm.wasm",
});

const paths = process.argv.slice(3);
const backups = [];
for (const path of paths) {
  const blob = await openAsBlob(path);
  Object.defineProperty(blob, "name", { value: path.split("/").pop() });
  backups.push(await BackupFile.open(blob));
}
backups.sort((a, b) => (a.lastModified < b.lastModified ? 1 : -1));
const [base, ...sources] = backups;

const db = new SQL.Database(await base.database());
const mediaPlan = new Map();
for (const entry of base.mediaEntries()) {
  mediaPlan.set(entry.name, { backup: base, entry });
}

const report = await mergeInto(db, SQL.Database, base, sources, mediaPlan, {
  inputFields: process.env.JWSYNC_INPUT_FIELDS || "keep",
});

const checkSources = [];
for (const b of backups) {
  checkSources.push({ label: b.file.name, db: new SQL.Database(await b.database()) });
}
const check = verify(db, checkSources, new Set(mediaPlan.keys()));
for (const s of checkSources) s.db.close();

const tags = [];
const stmt = db.prepare("SELECT Type, Name FROM Tag ORDER BY Type, Name");
while (stmt.step()) tags.push(stmt.getAsObject());
stmt.free();

console.log(JSON.stringify({
  base: base.file.name,
  counts: countsOf(db),
  tags,
  verifyOk: check.ok,
  verifyChecked: check.checked,
  missing: check.missing,
  integrityErrors: report.integrityErrors,
  mediaMembers: [...mediaPlan.keys()].length,
}));
db.close();
"""


def run_browser_engine(paths: list[Path], input_fields: str = "keep") -> dict:
    """Merge with the JavaScript engine and hand back what it produced."""
    with tempfile.TemporaryDirectory() as tmp:
        runner = Path(tmp) / "runner.mjs"
        runner.write_text(RUNNER, encoding="utf-8")
        result = subprocess.run(
            [NODE, str(runner), str(WEB), *[str(p) for p in paths]],
            capture_output=True,
            text=True,
            timeout=300,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "JWSYNC_INPUT_FIELDS": input_fields,
            },
        )
    if result.returncode != 0:
        pytest.fail(f"the browser engine failed:\n{result.stderr[-2000:]}")
    line = [ln for ln in result.stdout.splitlines() if ln.startswith("{")]
    if not line:
        pytest.fail(f"no result from the browser engine:\n{result.stdout[-2000:]}")
    return json.loads(line[-1])


def run_python_engine(
    paths: list[Path], tmp_path: Path, input_fields: str = "keep"
) -> dict:
    from jwsync.merge import MergeOptions

    stack = [Backup.open(p) for p in paths]
    try:
        ordered = sorted(stack, key=lambda b: b.sort_key(), reverse=True)
        base, sources = ordered[0], ordered[1:]
        work = tmp_path / "work"
        db_path, media, report = merge_backups(
            base, sources, work, MergeOptions(input_fields=input_fields)
        )
        out = tmp_path / "python-merged.jwlibrary"
        write_backup(out, db_path, media.members, base.manifest)
    finally:
        for backup in stack:
            backup.close()

    check = verify(out, paths)
    return {
        "base": base.path.name,
        "counts": report.totals_after,
        "verifyOk": check.ok,
        "verifyChecked": check.checked,
        "integrityErrors": report.integrity_errors,
        "output": out,
    }


def build_library(builder, name: str, device: str, stamp: str, seed: int):
    b = builder(f"{name}.jwlibrary", device, stamp)
    loc = b.location(BookNumber=40 + seed, ChapterNumber=5, KeySymbol="nwtsty")
    doc = b.location(DocumentId=100 + seed, KeySymbol="w26")
    mark = b.usermark(loc, f"mark-{name}")
    b.block_range(mark, identifier=1, start=0, end=5 + seed)
    b.note(
        f"note-{name}",
        title=f"title {name}",
        content=f"content {name}",
        location_id=loc,
        usermark_id=mark,
        last_modified=f"2026-0{seed + 1}-01T00:00:00Z",
    )
    b.tag(f"tag-{name}")
    b.tag("shared-tag")
    b.input_field(doc, f"q{seed}", f"answer from {name}")
    b.input_field(doc, "shared-question", f"answer from {name}")
    pub = b.location(KeySymbol="w26", Type=1, MepsLanguage=294)
    b.bookmark(pub, doc, slot=0, title=f"bookmark {name}")

    fp = b.media(f"audio bytes for {name}".encode(), f"{name}.mp3")
    shared = b.media(b"a recording both devices have", "shared.mp3")
    playlist = b.tag(f"Playlist {name}", type_=2)
    item = b.playlist_item(f"Song {name}")
    b.playlist_media(item, fp)
    b.tag_map(playlist, 0, playlist_item_id=item)

    common = b.tag("Shared playlist", type_=2)
    common_item = b.playlist_item("Common Song")
    b.playlist_media(common_item, shared)
    b.tag_map(common, 0, playlist_item_id=common_item)

    b.tag_map(b.tag(f"loctag-{name}"), 0, location_id=loc)
    return b.build()


@pytest.fixture
def pair(builder):
    return [
        build_library(builder, "phone", "Phone", NEWER, 0),
        build_library(builder, "tablet", "Tablet", OLDER, 1),
    ]


def test_both_engines_produce_the_same_row_counts(pair, tmp_path):
    js = run_browser_engine(pair)
    py = run_python_engine(pair, tmp_path)

    assert js["base"] == py["base"], (
        "the engines disagree about which backup is the base"
    )
    assert js["counts"] == py["counts"], (
        "the engines produced different row counts\n"
        f"browser: {json.dumps(js['counts'], indent=2, sort_keys=True)}\n"
        f"python : {json.dumps(py['counts'], indent=2, sort_keys=True)}"
    )


def test_both_engines_verify_the_same_way(pair, tmp_path):
    js = run_browser_engine(pair)
    py = run_python_engine(pair, tmp_path)

    assert js["verifyOk"] is True
    assert py["verifyOk"] is True
    assert js["verifyChecked"] == py["verifyChecked"]
    assert js["missing"] == []
    assert js["integrityErrors"] == []
    assert py["integrityErrors"] == []


def test_both_engines_agree_when_a_study_answer_is_overwritten(pair, tmp_path):
    js = run_browser_engine(pair, input_fields="overwrite")
    py = run_python_engine(pair, tmp_path, input_fields="overwrite")
    assert js["counts"] == py["counts"]


def test_the_browser_engine_is_idempotent(pair, tmp_path):
    """Merging the same libraries twice must not add anything."""
    once = run_browser_engine(pair)
    twice = run_browser_engine([*pair, pair[0]])
    assert once["counts"] == twice["counts"]


def test_the_browser_engine_keeps_the_same_tags(pair, tmp_path):
    js = run_browser_engine(pair)
    py = run_python_engine(pair, tmp_path)


    with Backup.open(py["output"]) as backup:
        conn = backup.connect()
        python_tags = [
            {"Type": r[0], "Name": r[1]}
            for r in conn.execute("SELECT Type, Name FROM Tag ORDER BY Type, Name")
        ]
        conn.close()
    assert js["tags"] == python_tags
