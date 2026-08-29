// The page's wiring: pick backups, merge them, check the result, save it.

import { BackupFile, ZipBuilder, rawSlice } from "./jwlibrary.js";
import { mergeInto } from "./merge.js";
import { verify } from "./verify.js";

const $ = (id) => document.getElementById(id);

let SQL = null;
let backups = [];
let merged = null; // { blob, name }

async function sqlEngine() {
  if (SQL) return SQL;
  // The single-file build inlines the wasm as base64 instead of fetching it.
  // A plain relative path is used rather than import.meta.url, because the
  // bundle runs this as a classic script, where import.meta is a parse error
  // even on a branch that never executes.
  const config = window.JWSYNC_WASM_BASE64
    ? { wasmBinary: base64ToBytes(window.JWSYNC_WASM_BASE64) }
    : { locateFile: (name) => `./vendor/${name}` };
  SQL = await window.initSqlJs(config);
  return SQL;
}

function base64ToBytes(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function megabytes(n) {
  return `${(n / 1e6).toFixed(1)} MB`;
}

function shortDate(iso) {
  if (!iso) return "date unknown";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function banner(target, kind, title, detail) {
  target.replaceChildren();
  const box = document.createElement("div");
  box.className = `banner ${kind}`;
  const strong = document.createElement("strong");
  strong.textContent = title;
  box.append(strong, document.createTextNode(detail));
  target.append(box);
}

function renderFiles() {
  const list = $("files");
  list.replaceChildren();

  for (const [index, backup] of backups.entries()) {
    const li = document.createElement("li");
    li.className = "file";

    const box = document.createElement("div");
    box.className = "grow";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = backup.deviceName || backup.file.name;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent =
      `${backup.file.name} · backed up ${shortDate(backup.lastModified)}` +
      ` · ${megabytes(backup.file.size)}`;
    box.append(name, meta);

    const drop = document.createElement("button");
    drop.className = "drop";
    drop.type = "button";
    drop.textContent = "×";
    drop.setAttribute("aria-label", `Remove ${backup.file.name}`);
    drop.addEventListener("click", () => {
      backups.splice(index, 1);
      renderFiles();
    });

    li.append(box, drop);
    list.append(li);
  }

  $("empty").hidden = backups.length > 0;
  $("merge").disabled = backups.length < 2;
}

async function addFiles(fileList) {
  const problems = [];
  for (const file of fileList) {
    if (backups.some((b) => b.file.name === file.name && b.file.size === file.size)) {
      continue;
    }
    try {
      backups.push(await BackupFile.open(file));
    } catch (error) {
      problems.push(`${file.name}: ${error.message}`);
    }
  }
  renderFiles();
  if (problems.length) {
    banner($("resultBanner"), "err", "Some files could not be opened", problems.join(" "));
    $("result").hidden = false;
    $("save").hidden = true;
  }
}

function reportText(report, check) {
  const lines = [];
  lines.push(`Started from : ${report.base} (${report.baseDevice})`);
  for (const source of report.sources) {
    lines.push("");
    lines.push(`Added from   : ${source.name} (${source.device})`);
    for (const [label, bucket] of [
      ["new", source.added],
      ["updated", source.updated],
      ["already there", source.reused],
      ["not added", source.skipped],
    ]) {
      const detail = Object.entries(bucket)
        .filter(([, n]) => n)
        .sort()
        .map(([table, n]) => `${table}=${n}`)
        .join("  ");
      if (detail) lines.push(`  ${label.padEnd(14)}${detail}`);
    }
    lines.push(
      `  media         added=${source.mediaAdded} already there=${source.mediaReused}`
    );
    for (const conflict of source.conflicts) {
      lines.push(`  ! ${conflict.detail} -> ${conflict.resolution}`);
    }
  }

  lines.push("");
  lines.push("In the combined file");
  for (const table of Object.keys(report.totalsAfter).sort()) {
    const before = report.totalsBefore[table] ?? 0;
    const after = report.totalsAfter[table];
    if (!after) continue;
    const added = after - before;
    lines.push(
      `  ${table.padEnd(34)}${String(after).padStart(7)}${added ? `  (+${added})` : ""}`
    );
  }

  lines.push("");
  lines.push("Checked and found in the combined file");
  for (const [table, n] of Object.entries(check.checked).sort()) {
    lines.push(`  ${table.padEnd(34)}${String(n).padStart(7)}`);
  }
  for (const missing of check.missing.slice(0, 40)) {
    lines.push(`  MISSING ${missing.table}: ${missing.description}`);
  }
  for (const file of check.mediaMissingFiles.slice(0, 20)) {
    lines.push(`  MISSING FILE ${file}`);
  }
  for (const error of report.integrityErrors) {
    lines.push(`  INTEGRITY ${error}`);
  }
  return lines.join("\n");
}

async function doMerge() {
  const progress = $("progress");
  const progressText = $("progressText");
  $("merge").disabled = true;
  progress.hidden = false;
  progress.removeAttribute("value");
  progressText.hidden = false;
  progressText.textContent = "Reading your backups…";
  $("result").hidden = true;

  try {
    const engine = await sqlEngine();

    // The most recently made backup becomes the starting point.
    const ordered = [...backups].sort((a, b) =>
      a.lastModified < b.lastModified ? 1 : -1
    );
    const [base, ...sources] = ordered;

    const db = new engine.Database(await base.database());
    const mediaPlan = new Map();
    for (const entry of base.mediaEntries()) {
      mediaPlan.set(entry.name, { backup: base, entry });
    }

    const report = await mergeInto(db, engine.Database, base, sources, mediaPlan, {
      inputFields: $("inputFields").value,
      onProgress: (message) => {
        progressText.textContent = message;
      },
    });

    progressText.textContent = "Checking that nothing was lost…";
    await new Promise((resolve) => setTimeout(resolve, 0));

    const checkSources = [];
    for (const backup of ordered) {
      checkSources.push({
        label: backup.file.name,
        db: new engine.Database(await backup.database()),
      });
    }
    const check = verify(db, checkSources, new Set(mediaPlan.keys()));
    for (const source of checkSources) source.db.close();

    progressText.textContent = "Writing the combined file…";
    const builder = new ZipBuilder();
    const manifest = JSON.parse(JSON.stringify(base.manifest));
    const stamp = new Date().toISOString().slice(0, 10);
    const name = `JW Library COMBINED ${stamp}.jwlibrary`;
    manifest.name = name;
    manifest.creationDate = new Date().toISOString();
    manifest.userDataBackup.deviceName = "jwsync combined";
    manifest.userDataBackup.hash = "";

    await builder.add("manifest.json", new TextEncoder().encode(JSON.stringify(manifest)));
    await builder.add(base.dbEntry.name, db.export());
    for (const [member, { backup, entry }] of mediaPlan) {
      builder.copyFrom(member, entry, await rawSlice(backup.file, entry));
    }
    db.close();

    merged = { blob: builder.finish("application/octet-stream"), name };

    $("report").textContent = reportText(report, check);
    $("save").hidden = false;
    $("result").hidden = false;

    const problems = report.integrityErrors.length + check.missing.length;
    if (check.ok && !report.integrityErrors.length) {
      banner(
        $("resultBanner"),
        "ok",
        "Done — everything is there.",
        `Every note, highlight, bookmark, tag and playlist from all ` +
          `${backups.length} backups was found in the combined file ` +
          `(${megabytes(merged.blob.size)}).`
      );
    } else {
      banner(
        $("resultBanner"),
        "warn",
        "Combined, but the check found problems.",
        `${problems} item(s) could not be confirmed. Open "What changed" below ` +
          `before you restore this anywhere.`
      );
    }
  } catch (error) {
    merged = null;
    $("save").hidden = true;
    $("report").textContent = "";
    banner($("resultBanner"), "err", "It did not work.", error.message);
    $("result").hidden = false;
  } finally {
    progress.hidden = true;
    progressText.hidden = true;
    $("merge").disabled = backups.length < 2;
  }
}

function save() {
  if (!merged) return;
  const url = URL.createObjectURL(merged.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = merged.name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

$("choose").addEventListener("click", () => $("picker").click());
$("picker").addEventListener("change", async (event) => {
  await addFiles(event.target.files);
  event.target.value = "";
});
$("merge").addEventListener("click", doMerge);
$("save").addEventListener("click", save);

renderFiles();
