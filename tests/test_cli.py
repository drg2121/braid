from __future__ import annotations

import json
from pathlib import Path

from jwsync.archive import Backup
from jwsync.cli import STATE_FILENAME, main

NEWER = "2026-08-01T00:00:00+0000"
OLDER = "2026-01-01T00:00:00+0000"


def make_pair(builder, tmp_path: Path) -> tuple[Path, Path]:
    a = builder("phone.jwlibrary", "Phone", NEWER)
    loc = a.location(BookNumber=40, ChapterNumber=5, KeySymbol="nwtsty")
    a.note("n-phone", content="from phone", location_id=loc)
    a.tag("phone-tag")
    phone = a.build()

    b = builder("tablet.jwlibrary", "Tablet", OLDER)
    loc_b = b.location(BookNumber=41, ChapterNumber=1, KeySymbol="nwtsty")
    b.note("n-tablet", content="from tablet", location_id=loc_b)
    b.tag("tablet-tag")
    tablet = b.build()
    return phone, tablet


def test_inspect_reports_counts_as_json(builder, tmp_path, capsys):
    phone, tablet = make_pair(builder, tmp_path)
    assert main(["inspect", str(phone), str(tablet), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {e["device"] for e in payload} == {"Phone", "Tablet"}
    assert payload[0]["counts"]["Note"] == 1


def test_merge_writes_an_archive_holding_both_libraries(builder, tmp_path, capsys):
    phone, tablet = make_pair(builder, tmp_path)
    out = tmp_path / "merged.jwlibrary"
    assert main(["merge", str(phone), str(tablet), "-o", str(out)]) == 0
    capsys.readouterr()

    with Backup.open(out) as backup:
        conn = backup.connect()
        guids = {r[0] for r in conn.execute("SELECT Guid FROM Note")}
        names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
        conn.close()
    assert guids == {"n-phone", "n-tablet"}
    assert names == {"phone-tag", "tablet-tag"}


def test_merge_refuses_to_clobber_an_existing_output(builder, tmp_path, capsys):
    phone, tablet = make_pair(builder, tmp_path)
    out = tmp_path / "merged.jwlibrary"
    out.write_bytes(b"existing")
    assert main(["merge", str(phone), str(tablet), "-o", str(out)]) == 1
    assert "already exists" in capsys.readouterr().err
    assert out.read_bytes() == b"existing"


def test_merge_overwrites_with_force(builder, tmp_path, capsys):
    phone, tablet = make_pair(builder, tmp_path)
    out = tmp_path / "merged.jwlibrary"
    out.write_bytes(b"existing")
    assert main(["merge", str(phone), str(tablet), "-o", str(out), "--force"]) == 0
    capsys.readouterr()
    assert out.read_bytes() != b"existing"


def test_merge_needs_two_files(builder, tmp_path, capsys):
    phone, _ = make_pair(builder, tmp_path)
    assert main(["merge", str(phone)]) == 2
    assert "at least two" in capsys.readouterr().err


def test_merge_writes_a_json_report_when_asked(builder, tmp_path, capsys):
    phone, tablet = make_pair(builder, tmp_path)
    out = tmp_path / "merged.jwlibrary"
    report = tmp_path / "report.json"
    main(["merge", str(phone), str(tablet), "-o", str(out), "--report", str(report)])
    capsys.readouterr()
    payload = json.loads(report.read_text())
    assert payload["baseDevice"] == "Phone"
    assert payload["sources"][0]["device"] == "Tablet"


def test_sync_merges_a_folder_and_records_state(builder, tmp_path, capsys):
    folder = tmp_path / "shared"
    folder.mkdir()

    a = builder("phone.jwlibrary", "Phone", NEWER)
    a.tag("phone-tag")
    a.build().rename(folder / "phone.jwlibrary")
    b = builder("tablet.jwlibrary", "Tablet", OLDER)
    b.tag("tablet-tag")
    b.build().rename(folder / "tablet.jwlibrary")

    assert main(["sync", str(folder)]) == 0
    capsys.readouterr()

    state = json.loads((folder / STATE_FILENAME).read_text())
    assert len(state["runs"]) == 1
    merged = Path(state["runs"][0]["output"])
    assert merged.exists()

    with Backup.open(merged) as backup:
        conn = backup.connect()
        names = {r[0] for r in conn.execute("SELECT Name FROM Tag")}
        conn.close()
    assert names == {"phone-tag", "tablet-tag"}


def test_sync_is_a_no_op_when_nothing_changed(builder, tmp_path, capsys):
    folder = tmp_path / "shared"
    folder.mkdir()
    builder("phone.jwlibrary", "Phone", NEWER).build().rename(folder / "phone.jwlibrary")
    builder("tablet.jwlibrary", "Tablet", OLDER).build().rename(
        folder / "tablet.jwlibrary"
    )

    main(["sync", str(folder)])
    capsys.readouterr()
    assert main(["sync", str(folder)]) == 0
    assert "nothing changed" in capsys.readouterr().out


def test_sync_ignores_its_own_previous_output(builder, tmp_path, capsys):
    folder = tmp_path / "shared"
    folder.mkdir()
    builder("phone.jwlibrary", "Phone", NEWER).build().rename(folder / "phone.jwlibrary")
    builder("tablet.jwlibrary", "Tablet", OLDER).build().rename(
        folder / "tablet.jwlibrary"
    )

    main(["sync", str(folder)])
    capsys.readouterr()
    main(["sync", str(folder), "--force"])
    capsys.readouterr()

    state = json.loads((folder / STATE_FILENAME).read_text())
    second = state["runs"][-1]
    assert set(second["inputs"]) == {"phone.jwlibrary", "tablet.jwlibrary"}


def test_sync_needs_at_least_two_backups(builder, tmp_path, capsys):
    folder = tmp_path / "shared"
    folder.mkdir()
    builder("phone.jwlibrary", "Phone", NEWER).build().rename(folder / "phone.jwlibrary")
    assert main(["sync", str(folder)]) == 1
    assert "need at least two" in capsys.readouterr().err


def test_a_corrupt_input_produces_a_message_not_a_traceback(tmp_path, capsys):
    bad = tmp_path / "bad.jwlibrary"
    bad.write_text("not a zip")
    other = tmp_path / "other.jwlibrary"
    other.write_text("also not a zip")
    assert main(["merge", str(bad), str(other), "-o", str(tmp_path / "o.jwlibrary")]) == 1
    assert "error:" in capsys.readouterr().err


def test_sync_never_overwrites_an_existing_backup_in_the_folder(
    builder, tmp_path, capsys
):
    folder = tmp_path / "shared"
    folder.mkdir()
    builder("phone.jwlibrary", "Phone", NEWER).build().rename(folder / "phone.jwlibrary")
    builder("tablet.jwlibrary", "Tablet", OLDER).build().rename(
        folder / "tablet.jwlibrary"
    )

    main(["sync", str(folder)])
    capsys.readouterr()
    first = Path(json.loads((folder / STATE_FILENAME).read_text())["runs"][-1]["output"])
    marker = first.read_bytes()

    # A second run in the same minute must not write over the first result.
    main(["sync", str(folder), "--force"])
    capsys.readouterr()
    second = Path(json.loads((folder / STATE_FILENAME).read_text())["runs"][-1]["output"])

    assert second != first
    assert first.exists()
    assert first.read_bytes() == marker
