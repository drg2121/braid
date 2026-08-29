"""Tests for the local web interface.

This is the interface most people will use, so its endpoints are covered the
same way the command line is. The HTTP layer is thin; the tests drive the
handler functions directly and, for the page itself, check the one thing that
silently breaks everything: escaping in the embedded JavaScript.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jwsync import webui
from jwsync.archive import Backup
from jwsync.local import DB_NAME, LocalLibrary, LocalLibraryError

NEWER = "2026-08-01T00:00:00+0000"
OLDER = "2026-01-01T00:00:00+0000"


@pytest.fixture
def two_backups(builder, tmp_path):
    folder = tmp_path / "shared"
    folder.mkdir()

    a = builder("phone.jwlibrary", "Phone", NEWER)
    a.tag("phone-tag")
    a.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty")
    a.build().rename(folder / "phone.jwlibrary")

    b = builder("tablet.jwlibrary", "Tablet", OLDER)
    b.tag("tablet-tag")
    b.location(BookNumber=41, ChapterNumber=1, KeySymbol="nwtsty")
    b.build().rename(folder / "tablet.jwlibrary")
    return folder


# -- the page itself --------------------------------------------------------

def test_the_page_javascript_survives_python_string_handling():
    """PAGE is a raw string; if it stops being one, escapes break the script.

    A JavaScript "\\n" written into an ordinary Python string becomes a real
    newline, which lands inside a JS string literal and makes the browser throw
    a SyntaxError -- taking the whole interface down with no visible error.
    """
    source = Path(webui.__file__).read_text(encoding="utf-8")
    assert 'PAGE = r"""' in source, "PAGE must stay a raw string"

    # No literal newline may appear inside a quoted JavaScript string.
    for line in webui.PAGE.splitlines():
        assert line.count('"') % 2 == 0 or "//" in line or "<" in line


def test_the_page_is_self_contained():
    assert "http://" not in webui.PAGE.replace("http://127.0.0.1", "")
    assert "<script src" not in webui.PAGE
    assert "<link" not in webui.PAGE


def test_the_page_defines_a_dark_palette():
    assert "prefers-color-scheme: dark" in webui.PAGE


# -- scanning ---------------------------------------------------------------

def test_scan_lists_each_backup_with_its_device(two_backups):
    found = webui._scan(two_backups)
    devices = {entry["device"] for entry in found}
    assert devices == {"Phone", "Tablet"}
    assert all(entry["schemaVersion"] == 16 for entry in found)
    assert all(entry["sizeMb"] >= 0 for entry in found)


def test_scan_reports_an_unreadable_file_instead_of_failing(two_backups):
    (two_backups / "broken.jwlibrary").write_text("not a zip")
    found = webui._scan(two_backups)
    assert len(found) == 3
    broken = next(e for e in found if e["name"] == "broken.jwlibrary")
    assert "unreadable" in broken["device"]


# -- merging ----------------------------------------------------------------

def test_merge_endpoint_writes_and_verifies(two_backups):
    paths = sorted(str(p) for p in two_backups.glob("*.jwlibrary"))
    result = webui._merge({"files": paths, "inputFields": "keep"})

    assert result["verified"] is True
    assert "PASS" in result["text"]
    out = Path(result["output"])
    assert out.is_file()

    with Backup.open(out) as backup:
        conn = backup.connect()
        names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
        conn.close()
    assert names == {"phone-tag", "tablet-tag"}


def test_merge_endpoint_needs_two_files(two_backups):
    one = str(next(two_backups.glob("*.jwlibrary")))
    with pytest.raises(ValueError, match="at least two"):
        webui._merge({"files": [one]})


def test_merge_endpoint_does_not_overwrite_an_earlier_result(two_backups):
    paths = sorted(str(p) for p in two_backups.glob("*.jwlibrary"))
    first = Path(webui._merge({"files": paths})["output"])
    marker = first.read_bytes()
    second = Path(webui._merge({"files": paths})["output"])
    assert second != first
    assert first.read_bytes() == marker


# -- the local library ------------------------------------------------------

@pytest.fixture
def fake_local(builder, tmp_path, monkeypatch):
    b = builder("seed.jwlibrary", "Computer", NEWER)
    b.tag("on-this-computer")
    b.location(BookNumber=42, ChapterNumber=2, KeySymbol="nwtsty")
    seed = b.build()

    folder = tmp_path / "Userdata"
    folder.mkdir()
    with Backup.open(seed) as backup:
        (folder / DB_NAME).write_bytes(backup.db_path.read_bytes())

    library = LocalLibrary(folder)
    monkeypatch.setattr(webui, "find_libraries", lambda: [library])
    monkeypatch.setattr("jwsync.local.jw_library_is_running", lambda: False)
    return library


def test_local_info_describes_the_installation(fake_local):
    info = webui._local_info()
    assert info["found"] is True
    assert info["path"] == str(fake_local.path)
    assert info["running"] is False
    assert info["counts"] > 0


def test_local_info_when_there_is_no_installation(monkeypatch):
    monkeypatch.setattr(webui, "find_libraries", lambda: [])
    assert webui._local_info() == {"found": False}


def test_local_pull_adds_the_computer_to_the_folder(fake_local, two_backups):
    result = webui._local_pull({"folder": str(two_backups)})
    out = Path(result["output"])
    assert out.is_file()
    assert len(list(two_backups.glob("*.jwlibrary"))) == 3


def test_local_pull_rejects_a_folder_that_is_not_there(fake_local, tmp_path):
    with pytest.raises(LocalLibraryError, match="not a folder"):
        webui._local_pull({"folder": str(tmp_path / "nowhere")})


def test_local_push_installs_and_reports_the_safety_copy(fake_local, two_backups):
    paths = sorted(str(p) for p in two_backups.glob("*.jwlibrary"))
    merged = webui._merge({"files": paths})["output"]

    result = webui._local_push({"backup": merged})
    assert Path(result["safetyCopy"]).is_dir()

    import sqlite3

    conn = sqlite3.connect(f"file:{fake_local.db_path}?mode=ro", uri=True)
    names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
    conn.close()
    assert {"phone-tag", "tablet-tag"} <= names


def test_local_push_refuses_while_the_app_is_open(fake_local, two_backups, monkeypatch):
    paths = sorted(str(p) for p in two_backups.glob("*.jwlibrary"))
    merged = webui._merge({"files": paths})["output"]
    monkeypatch.setattr("jwsync.local.jw_library_is_running", lambda: True)

    with pytest.raises(LocalLibraryError, match="running"):
        webui._local_push({"backup": merged})


def test_local_push_refuses_a_file_that_is_not_a_backup(fake_local, tmp_path):
    from jwsync.archive import ArchiveError

    bogus = tmp_path / "bogus.jwlibrary"
    bogus.write_text("not a zip")
    with pytest.raises(ArchiveError, match="not a ZIP"):
        webui._local_push({"backup": str(bogus)})


def test_local_push_refuses_a_missing_file(fake_local, tmp_path):
    with pytest.raises(LocalLibraryError, match="does not exist"):
        webui._local_push({"backup": str(tmp_path / "gone.jwlibrary")})
