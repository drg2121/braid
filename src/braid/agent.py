"""Run the watcher in the background, at login, without a terminal open.

macOS uses launchd, Linux uses systemd --user, Windows uses Task Scheduler.
Only the file is written here; loading it is a separate, explicit step, because
installing something that starts itself at login is not a change to make
quietly.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from xml.sax.saxutils import escape

LABEL = "com.braid.watch"


def launchd_plist(folder: Path, interval: int, executable: str) -> str:
    args = [executable, "watch", str(folder), "--interval", str(interval)]
    arg_xml = "\n".join(f"    <string>{escape(a)}</string>" for a in args)
    log = Path.home() / "Library" / "Logs" / "braid.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{arg_xml}
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{escape(str(log))}</string>
  <key>StandardErrorPath</key>
  <string>{escape(str(log))}</string>
</dict>
</plist>
"""


def systemd_unit(folder: Path, interval: int, executable: str) -> str:
    return f"""[Unit]
Description=braid -- merge JW Library backups in {folder}

[Service]
Type=simple
ExecStart={executable} watch {folder} --interval {interval}
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
"""


def windows_command(folder: Path, interval: int, executable: str) -> str:
    return (
        f'schtasks /Create /TN "{LABEL}" /SC ONLOGON /RL LIMITED '
        f'/TR "\\"{executable}\\" watch \\"{folder}\\" --interval {interval}"'
    )


def install(folder: Path, interval: int, executable: str | None = None) -> dict:
    """Write the service definition and describe how to activate it.

    Returns a dict with the path written (if any) and the command that will
    start it. Nothing is loaded or started here.
    """
    folder = Path(folder).expanduser().resolve()
    executable = executable or _executable()
    system = platform.system()

    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(launchd_plist(folder, interval, executable), encoding="utf-8")
        return {
            "system": "macOS (launchd)",
            "path": str(path),
            "activate": f"launchctl load -w {path}",
            "deactivate": f"launchctl unload -w {path}",
            "logs": str(Path.home() / "Library" / "Logs" / "braid.log"),
        }

    if system == "Linux":
        path = Path.home() / ".config" / "systemd" / "user" / f"{LABEL}.service"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(systemd_unit(folder, interval, executable), encoding="utf-8")
        return {
            "system": "Linux (systemd --user)",
            "path": str(path),
            "activate": (
                f"systemctl --user daemon-reload && "
                f"systemctl --user enable --now {LABEL}.service"
            ),
            "deactivate": f"systemctl --user disable --now {LABEL}.service",
            "logs": f"journalctl --user -u {LABEL}.service -f",
        }

    return {
        "system": f"{system} (Task Scheduler)",
        "path": "",
        "activate": windows_command(folder, interval, executable),
        "deactivate": f'schtasks /Delete /TN "{LABEL}" /F',
        "logs": "the console window the task opens",
    }


def _executable() -> str:
    """Path to the installed ``braid`` command, falling back to the module."""
    candidate = Path(sys.executable).with_name("braid")
    if candidate.is_file():
        return str(candidate)
    return f"{sys.executable} -m braid"


__all__ = ["LABEL", "install", "launchd_plist", "systemd_unit", "windows_command"]
