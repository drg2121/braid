"""A small local web interface for braid.

The page is served from the standard library only and binds to localhost. It
works on folders rather than uploads: JW Library backups routinely run to
hundreds of megabytes, and the natural workflow is a folder that iCloud
Drive, Google Drive or Dropbox already syncs between the devices.
"""

from __future__ import annotations

import json
import tempfile
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .archive import Backup, unique_path, write_backup
from .local import (
    LocalLibrary,
    LocalLibraryError,
    default_device_name,
    find_libraries,
)
from .merge import MergeOptions, merge_backups
from .verify import verify

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>braid</title>
<style>
  :root {
    --bg: #f6f6f8; --panel: #ffffff; --ink: #1a1a1f; --muted: #5f6069;
    --line: #e2e2e8; --accent: #5a2d8c; --accent-ink: #ffffff;
    --ok: #1c7c47; --warn: #9a5b00; --err: #b3261e;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #16161a; --panel: #1f1f25; --ink: #ececf1; --muted: #a0a1ac;
      --line: #32323c; --accent: #b490dd; --accent-ink: #16161a;
      --ok: #6ed09b; --warn: #e0a253; --err: #f2857d;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 2rem 1rem; background: var(--bg); color: var(--ink);
    font: 15px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  main { max-width: 60rem; margin: 0 auto; }
  h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
  p.lede { color: var(--muted); margin: 0 0 1.5rem; }
  section {
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    padding: 1.25rem; margin-bottom: 1rem;
  }
  label { display: block; font-weight: 600; margin-bottom: .35rem; }
  input[type=text], select {
    width: 100%; padding: .55rem .7rem; border: 1px solid var(--line);
    border-radius: 8px; background: var(--bg); color: var(--ink); font: inherit;
  }
  button {
    background: var(--accent); color: var(--accent-ink); border: 0;
    border-radius: 8px; padding: .6rem 1.1rem; font: inherit; font-weight: 600;
    cursor: pointer;
  }
  button[disabled] { opacity: .5; cursor: default; }
  button.secondary { background: transparent; color: var(--accent); border: 1px solid var(--line); }
  .row { display: flex; gap: .6rem; align-items: flex-end; flex-wrap: wrap; }
  .row > div { flex: 1 1 16rem; }
  ul.files { list-style: none; padding: 0; margin: .5rem 0 0; }
  ul.files li {
    display: flex; gap: .6rem; align-items: baseline; padding: .5rem 0;
    border-top: 1px solid var(--line);
  }
  ul.files li:first-child { border-top: 0; }
  .name { font-weight: 600; }
  .meta { color: var(--muted); font-size: .87rem; }
  pre {
    background: var(--bg); border: 1px solid var(--line); border-radius: 8px;
    padding: .9rem; overflow-x: auto; font-size: .85rem; margin: 0;
  }
  .status { margin-top: .8rem; font-weight: 600; }
  .ok { color: var(--ok); } .warn { color: var(--warn); } .err { color: var(--err); }
  .hint { color: var(--muted); font-size: .87rem; margin-top: .5rem; }
</style>
</head>
<body>
<main>
  <h1>braid</h1>
  <p class="lede">Merge JW Library backups from several devices into one file you
  can restore everywhere.</p>

  <section>
    <label for="folder">Folder holding your <code>.jwlibrary</code> backups</label>
    <div class="row">
      <div><input type="text" id="folder" placeholder="~/Library/Mobile Documents/… /JW backups"></div>
      <button id="scan" class="secondary">Scan</button>
    </div>
    <p class="hint">A folder that iCloud Drive, Google Drive or Dropbox already
    syncs works well: export a backup from each device into it, then merge.</p>
    <ul class="files" id="files"></ul>
  </section>

  <section id="localCard" hidden>
    <label>JW Library on this computer</label>
    <div class="meta" id="localInfo"></div>
    <div class="row" style="margin-top:.8rem">
      <div style="flex:0 0 auto">
        <button id="pull" class="secondary">Add it to the folder</button>
      </div>
      <div style="flex:0 0 auto">
        <button id="push" class="secondary">Put the merged library back into it</button>
      </div>
    </div>
    <p class="hint" id="localHint"></p>
  </section>

  <section>
    <div class="row">
      <div>
        <label for="inputFields">If a study answer differs between devices</label>
        <select id="inputFields">
          <option value="keep">Keep the newest backup's answer</option>
          <option value="overwrite">Take the other device's answer</option>
        </select>
      </div>
      <div>
        <label for="device">Device name for the merged file</label>
        <input type="text" id="device" placeholder="merged">
      </div>
      <div style="flex:0 0 auto"><button id="merge" disabled>Merge selected</button></div>
    </div>
    <div class="status" id="status"></div>
  </section>

  <section id="reportBox" hidden>
    <label>Report</label>
    <pre id="report"></pre>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
let found = [];

async function scan() {
  const folder = $("folder").value.trim();
  if (!folder) return;
  $("status").textContent = "Scanning…";
  $("status").className = "status";
  try {
    const res = await fetch("/api/scan?folder=" + encodeURIComponent(folder));
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "scan failed");
    found = data.files;
    render();
    $("status").textContent = found.length + " backup(s) found.";
  } catch (err) {
    found = []; render();
    $("status").textContent = err.message;
    $("status").className = "status err";
  }
}

function render() {
  const list = $("files");
  list.replaceChildren();
  for (const f of found) {
    const li = document.createElement("li");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = true; cb.dataset.path = f.path;
    cb.addEventListener("change", updateButton);
    const box = document.createElement("div");
    const name = document.createElement("div");
    name.className = "name"; name.textContent = f.name;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${f.device || "unknown device"} · schema v${f.schemaVersion}`
      + ` · modified ${f.lastModified || "?"} · ${f.sizeMb} MB`;
    box.append(name, meta);
    li.append(cb, box);
    list.append(li);
  }
  updateButton();
}

function selected() {
  return [...document.querySelectorAll("#files input:checked")].map(c => c.dataset.path);
}
function updateButton() { $("merge").disabled = selected().length < 2; }

async function merge() {
  const paths = selected();
  $("merge").disabled = true;
  $("status").textContent = "Merging… large libraries take a minute.";
  $("status").className = "status";
  try {
    const res = await fetch("/api/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        files: paths,
        inputFields: $("inputFields").value,
        deviceName: $("device").value.trim(),
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "merge failed");
    $("reportBox").hidden = false;
    $("report").textContent = data.text;
    const bad = data.integrityErrors.length || !data.verified;
    $("status").textContent = data.verified
      ? "Merged and verified — every item from every backup is in " + data.output
      : "Merged into " + data.output + ", but the check found problems. Read the report.";
    $("status").className = "status " + (bad ? "warn" : "ok");
    lastMerged = data.output;
    loadLocal();
  } catch (err) {
    $("status").textContent = err.message;
    $("status").className = "status err";
  } finally { updateButton(); }
}

let lastMerged = null;

async function loadLocal() {
  try {
    const res = await fetch("/api/local");
    const data = await res.json();
    if (!data.found) return;
    $("localCard").hidden = false;
    $("localInfo").textContent =
      `${data.path} — schema v${data.schemaVersion}`
      + ` · ${data.counts} items · app is ${data.running ? "open" : "closed"}`;
    $("push").disabled = data.running || !lastMerged;
    $("localHint").textContent = data.running
      ? "Quit JW Library before putting a merged library back into it — writing "
        + "while it is open can damage it."
      : "Your current library is copied aside before anything is written.";
  } catch (err) { /* no local library is a normal situation */ }
}

async function pullLocal() {
  const folder = $("folder").value.trim();
  if (!folder) { $("status").textContent = "Choose a folder first."; return; }
  $("pull").disabled = true;
  $("status").textContent = "Exporting this computer's library…";
  $("status").className = "status";
  try {
    const res = await fetch("/api/local/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "export failed");
    $("status").textContent = "Added " + data.output;
    $("status").className = "status ok";
    await scan();
  } catch (err) {
    $("status").textContent = err.message;
    $("status").className = "status err";
  } finally { $("pull").disabled = false; }
}

async function pushLocal() {
  if (!lastMerged) return;
  if (!confirm(
    "This replaces the JW Library on this computer with the merged library.\n\n"
    + "Your current library is copied aside first. Continue?")) return;
  $("push").disabled = true;
  $("status").textContent = "Updating this computer's library…";
  $("status").className = "status";
  try {
    const res = await fetch("/api/local/push", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup: lastMerged }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "update failed");
    $("status").textContent =
      "This computer is up to date. Previous library saved to " + data.safetyCopy;
    $("status").className = "status ok";
  } catch (err) {
    $("status").textContent = err.message;
    $("status").className = "status err";
  } finally { loadLocal(); }
}

$("pull").addEventListener("click", pullLocal);
$("push").addEventListener("click", pushLocal);
$("scan").addEventListener("click", scan);
$("folder").addEventListener("keydown", (e) => { if (e.key === "Enter") scan(); });
$("merge").addEventListener("click", merge);

try {
  const saved = localStorage.getItem("braid.folder");
  if (saved) { $("folder").value = saved; scan(); }
} catch (err) { /* private windows and blocked storage are fine */ }

$("folder").addEventListener("change", () => {
  try { localStorage.setItem("braid.folder", $("folder").value.trim()); }
  catch (err) { /* nothing to do if storage is unavailable */ }
});

loadLocal();
</script>
</body>
</html>
"""


def _scan(folder: Path) -> list[dict]:
    out = []
    for path in sorted(folder.glob("*.jwlibrary")):
        try:
            with Backup.open(path) as backup:
                out.append(
                    {
                        "path": str(path),
                        "name": path.name,
                        "device": backup.manifest.device_name,
                        "schemaVersion": backup.manifest.schema_version,
                        "lastModified": backup.manifest.last_modified_date,
                        "sizeMb": round(path.stat().st_size / 1e6, 1),
                    }
                )
        except Exception as exc:  # a stray or half-written file should not stop the scan
            out.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "device": f"unreadable: {exc}",
                    "schemaVersion": 0,
                    "lastModified": "",
                    "sizeMb": round(path.stat().st_size / 1e6, 1),
                }
            )
    return out


def _merge(payload: dict) -> dict:
    paths = [Path(p) for p in payload.get("files", [])]
    if len(paths) < 2:
        raise ValueError("select at least two backups")

    stack: list[Backup] = []
    try:
        for path in paths:
            stack.append(Backup.open(path))
        ordered = sorted(stack, key=lambda b: b.sort_key(), reverse=True)
        base, sources = ordered[0], ordered[1:]

        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        output = unique_path(
            paths[0].parent / f"UserdataBackup_{stamp}_merged.jwlibrary"
        )
        options = MergeOptions(input_fields=payload.get("inputFields", "keep"))

        with tempfile.TemporaryDirectory(prefix="braid-web-") as tmp:
            db_path, media, report = merge_backups(base, sources, Path(tmp), options)
            manifest = base.manifest
            manifest.device_name = (
                payload.get("deviceName") or f"{base.manifest.device_name} (merged)"
            )
            write_backup(output, db_path, media.members, manifest)
            report.output = str(output)

        # Check the result independently before telling anyone it is safe.
        check = verify(output, paths)

        return {
            "output": str(output),
            "text": report.to_text() + "\n\n" + check.to_text(),
            "integrityErrors": report.integrity_errors,
            "verified": check.ok,
        }
    finally:
        for backup in stack:
            backup.close()


def _local_info() -> dict:
    found = find_libraries()
    if not found:
        return {"found": False}
    library = found[0]
    counts = library.counts()
    return {
        "found": True,
        "path": str(library.path),
        "schemaVersion": library.schema_version(),
        "running": library.is_running(),
        "counts": sum(counts.values()),
    }


def _local_pull(payload: dict) -> dict:
    found = find_libraries()
    if not found:
        raise LocalLibraryError("no JW Library installation found on this computer")
    folder = Path(payload.get("folder", "")).expanduser()
    if not folder.is_dir():
        raise LocalLibraryError(f"{folder} is not a folder")
    name = default_device_name()
    out = found[0].export(
        folder / f"UserdataBackup_{name}_local.jwlibrary", device_name=name
    )
    return {"output": str(out)}


def _local_push(payload: dict) -> dict:
    found = find_libraries()
    if not found:
        raise LocalLibraryError("no JW Library installation found on this computer")
    library: LocalLibrary = found[0]
    backup = Path(payload.get("backup", "")).expanduser()
    if not backup.is_file():
        raise LocalLibraryError(f"{backup} does not exist")

    check = verify(backup, [backup])
    if not check.ok:
        raise LocalLibraryError(
            f"{backup.name} does not verify against itself; refusing to install it"
        )
    result = library.install(backup)
    return {"safetyCopy": result["safetyCopy"], "mediaCopied": result["mediaCopied"]}


class Handler(BaseHTTPRequestHandler):
    server_version = "braid"

    def log_message(self, fmt: str, *args: object) -> None:  # quieter console
        pass

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/local":
            try:
                self._json(200, _local_info())
            except Exception as exc:
                self._json(200, {"found": False, "error": str(exc)})
            return

        if parsed.path == "/api/scan":
            folder = Path(
                parse_qs(parsed.query).get("folder", [""])[0]
            ).expanduser()
            if not folder.is_dir():
                self._json(400, {"error": f"{folder} is not a folder"})
                return
            self._json(200, {"files": _scan(folder)})
            return

        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        handlers = {
            "/api/merge": _merge,
            "/api/local/pull": _local_pull,
            "/api/local/push": _local_push,
        }
        handler = handlers.get(route)
        if handler is None:
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._json(200, handler(payload))
        except Exception as exc:
            self._json(400, {"error": str(exc)})


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"braid is running at {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


__all__ = ["serve"]
