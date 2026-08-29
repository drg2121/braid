"""Tests for the folder watcher and the background-service definitions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jwsync import agent
from jwsync.archive import Backup
from jwsync.watch import (
    HISTORY_DIRNAME,
    STABLE_OUTPUT_NAME,
    STATE_FILENAME,
    inputs_for,
    merge_folder,
    pending_downloads,
    read_state,
    snapshot,
    watch,
)

NEWER = "2026-08-01T00:00:00+0000"
OLDER = "2026-01-01T00:00:00+0000"


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "shared"
    f.mkdir()
    return f


def drop(builder, folder: Path, name: str, device: str, stamp: str, tag: str) -> Path:
    b = builder(f"{name}.jwlibrary", device, stamp)
    b.tag(tag)
    b.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty")
    built = b.build()
    target = folder / f"{name}.jwlibrary"
    built.rename(target)
    return target


def log_lines() -> tuple[list[str], object]:
    lines: list[str] = []
    return lines, lines.append


def test_a_single_backup_is_not_merged(builder, folder):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    lines, log = log_lines()
    assert watch(folder, once=True, log=log) == 0
    assert not (folder / STABLE_OUTPUT_NAME).exists()
    assert any("nothing to merge yet" in line for line in lines)


def test_a_second_backup_triggers_a_merge_under_a_stable_name(builder, folder):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    drop(builder, folder, "tablet", "Tablet", OLDER, "tablet-tag")

    lines, log = log_lines()
    assert watch(folder, once=True, log=log) == 0

    merged = folder / STABLE_OUTPUT_NAME
    assert merged.is_file()
    assert any("verified" in line for line in lines)

    with Backup.open(merged) as backup:
        conn = backup.connect()
        names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
        conn.close()
    assert names == {"phone-tag", "tablet-tag"}


def test_an_unchanged_folder_is_not_merged_again(builder, folder):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    drop(builder, folder, "tablet", "Tablet", OLDER, "tablet-tag")

    watch(folder, once=True, log=lambda _: None)
    first = (folder / STABLE_OUTPUT_NAME).stat().st_mtime_ns

    lines, log = log_lines()
    watch(folder, once=True, log=log)
    assert any("up to date" in line for line in lines)
    assert (folder / STABLE_OUTPUT_NAME).stat().st_mtime_ns == first


def test_a_new_export_from_a_device_is_picked_up(builder, folder):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    drop(builder, folder, "tablet", "Tablet", OLDER, "tablet-tag")
    watch(folder, once=True, log=lambda _: None)

    # The tablet exports again, now with an extra tag.
    b = builder("tablet2.jwlibrary", "Tablet", "2026-09-01T00:00:00+0000")
    b.tag("tablet-tag")
    b.tag("brand-new-tag")
    b.build().rename(folder / "tablet.jwlibrary")

    lines, log = log_lines()
    watch(folder, once=True, log=log)
    assert any("merged" in line for line in lines)

    with Backup.open(folder / STABLE_OUTPUT_NAME) as backup:
        conn = backup.connect()
        names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
        conn.close()
    assert "brand-new-tag" in names
    assert "phone-tag" in names  # nothing from the first merge was lost


def test_state_survives_a_restart(builder, folder):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    drop(builder, folder, "tablet", "Tablet", OLDER, "tablet-tag")
    watch(folder, once=True, log=lambda _: None)

    state_file = folder / HISTORY_DIRNAME / STATE_FILENAME
    assert state_file.is_file()
    recorded = json.loads(state_file.read_text())
    assert {e["name"] for e in recorded["merged"]} == {
        "phone.jwlibrary",
        "tablet.jwlibrary",
    }
    assert read_state(folder) == snapshot(folder, {STABLE_OUTPUT_NAME})


def test_history_keeps_a_dated_copy(builder, folder):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    drop(builder, folder, "tablet", "Tablet", OLDER, "tablet-tag")
    watch(folder, once=True, log=lambda _: None)

    history = list((folder / HISTORY_DIRNAME).glob("merged-*.jwlibrary"))
    assert len(history) == 1
    assert history[0].stat().st_size > 0


def test_history_can_be_turned_off(builder, folder):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    drop(builder, folder, "tablet", "Tablet", OLDER, "tablet-tag")
    watch(folder, once=True, keep_history=False, log=lambda _: None)
    assert not list((folder / HISTORY_DIRNAME).glob("merged-*.jwlibrary"))


def test_the_merged_output_is_not_treated_as_a_device_backup(builder, folder):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    drop(builder, folder, "tablet", "Tablet", OLDER, "tablet-tag")
    watch(folder, once=True, log=lambda _: None)

    seen = {f.name for f in snapshot(folder, {STABLE_OUTPUT_NAME})}
    assert STABLE_OUTPUT_NAME not in seen

    # It is still folded back in as an input, so accumulated history survives.
    assert folder / STABLE_OUTPUT_NAME in inputs_for(folder, accumulate=True)
    assert folder / STABLE_OUTPUT_NAME not in inputs_for(folder, accumulate=False)


def test_fresh_mode_rebuilds_from_device_backups_only(builder, folder):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    drop(builder, folder, "tablet", "Tablet", OLDER, "tablet-tag")
    watch(folder, once=True, log=lambda _: None)

    # A device backup disappears from the folder.
    (folder / "tablet.jwlibrary").unlink()
    drop(builder, folder, "laptop", "Laptop", OLDER, "laptop-tag")

    merge_folder(folder, accumulate=False, keep_history=False)
    with Backup.open(folder / STABLE_OUTPUT_NAME) as backup:
        conn = backup.connect()
        names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
        conn.close()
    assert names == {"phone-tag", "laptop-tag"}
    assert "tablet-tag" not in names


def test_icloud_placeholders_are_reported(builder, folder):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    drop(builder, folder, "tablet", "Tablet", OLDER, "tablet-tag")
    (folder / ".laptop.jwlibrary.icloud").write_bytes(b"placeholder")

    assert pending_downloads(folder) == ["laptop.jwlibrary"]

    lines, log = log_lines()
    watch(folder, once=True, log=log)
    assert any("waiting for the cloud to download" in line for line in lines)
    # The placeholder must not be mistaken for a backup.
    assert not any("merge failed" in line for line in lines)


def test_a_broken_backup_does_not_crash_the_watcher(builder, folder):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    (folder / "corrupt.jwlibrary").write_text("this is not a zip")

    lines, log = log_lines()
    assert watch(folder, once=True, log=log) == 0
    assert any("merge failed" in line for line in lines)


def test_a_change_must_settle_before_a_continuous_watch_merges(
    builder, folder, monkeypatch
):
    drop(builder, folder, "phone", "Phone", NEWER, "phone-tag")
    drop(builder, folder, "tablet", "Tablet", OLDER, "tablet-tag")

    polls = {"n": 0}

    def fake_sleep(_seconds):
        polls["n"] += 1
        if polls["n"] >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr("jwsync.watch.time.sleep", fake_sleep)
    lines, log = log_lines()
    watch(folder, interval=0, log=log)

    settle = [i for i, ln in enumerate(lines) if "letting it settle" in ln]
    merge = [i for i, ln in enumerate(lines) if "merged" in ln]
    assert settle and merge and settle[0] < merge[0]


# -- background service definitions ----------------------------------------


def test_launchd_plist_is_valid_xml_and_names_the_folder(folder):
    import plistlib

    text = agent.launchd_plist(folder, 45, "/usr/local/bin/jwsync")
    parsed = plistlib.loads(text.encode())
    assert parsed["Label"] == agent.LABEL
    assert parsed["ProgramArguments"][:3] == [
        "/usr/local/bin/jwsync",
        "watch",
        str(folder),
    ]
    assert "45" in parsed["ProgramArguments"]
    assert parsed["RunAtLoad"] is True


def test_launchd_plist_escapes_a_folder_with_an_ampersand(tmp_path):
    import plistlib

    odd = tmp_path / "JW & backups"
    odd.mkdir()
    parsed = plistlib.loads(agent.launchd_plist(odd, 30, "jwsync").encode())
    assert str(odd) in parsed["ProgramArguments"]


def test_systemd_unit_mentions_the_command(folder):
    unit = agent.systemd_unit(folder, 60, "/usr/bin/jwsync")
    assert f"ExecStart=/usr/bin/jwsync watch {folder} --interval 60" in unit


def test_install_writes_a_definition_but_does_not_start_it(
    folder, tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    info = agent.install(folder, 30, executable="jwsync")
    assert "activate" in info and info["activate"]
    if info["path"]:
        assert Path(info["path"]).is_file()
