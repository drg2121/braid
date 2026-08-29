// The page's wiring: choose whose library, add backups, combine, remember.

import { BackupFile, ZipBuilder, rawSlice } from "./jwlibrary.js";
import { mergeInto } from "./merge.js";
import {
  createPerson,
  currentPersonId,
  deletePerson,
  forgetLibrary,
  getPerson,
  listPeople,
  rememberCurrentPerson,
  rememberLibrary,
  renamePerson,
  requestPersistence,
  usage,
} from "./store.js";
import { verify } from "./verify.js";

const $ = (id) => document.getElementById(id);

// Rows worth showing as a headline; the rest stay in the detailed report.
const HEADLINE = [
  ["UserMark", "highlights"],
  ["Note", "notes"],
  ["Bookmark", "bookmarks"],
  ["Tag", "tags"],
  ["PlaylistItem", "playlist items"],
];

let SQL = null;
let people = [];
let personId = null;
let added = []; // BackupFile objects picked this visit
let merged = null; // { blob, name }
let storeBroken = false;

// -- helpers ---------------------------------------------------------------

async function sqlEngine() {
  if (SQL) return SQL;
  // The single-file build inlines the wasm as base64 instead of fetching it.
  // A plain relative path is used rather than import.meta.url, because the
  // bundle runs this as a classic script, where import.meta is a parse error
  // even on a branch that never executes.
  const config = window.BRAID_WASM_BASE64
    ? { wasmBinary: base64ToBytes(window.BRAID_WASM_BASE64) }
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

const megabytes = (n) => `${(n / 1e6).toFixed(1)} MB`;

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

function say(kind, title, detail, { showSave = false } = {}) {
  banner($("resultBanner"), kind, title, detail);
  $("save").hidden = !showSave;
  $("result").hidden = false;
}

// -- people ----------------------------------------------------------------

function currentPerson() {
  return people.find((p) => p.id === personId) || null;
}

async function loadPeople() {
  try {
    people = await listPeople();
  } catch (error) {
    storeBroken = true;
    people = [];
    $("person").hidden = true;
    $("libraryCard").hidden = true;
    $("storageNote").textContent =
      `This browser cannot remember anything (${error.message}), so you will` +
      " need to add a backup from every device each time. Combining still works.";
    return;
  }

  if (!people.length) {
    people = [await createPerson("Me")];
  }
  const wanted = currentPersonId();
  personId = people.some((p) => p.id === wanted) ? wanted : people[0].id;
  rememberCurrentPerson(personId);
  renderPeople();
}

function renderPeople() {
  const select = $("person");
  select.replaceChildren();
  for (const person of people) {
    const option = document.createElement("option");
    option.value = person.id;
    option.textContent = person.name;
    option.selected = person.id === personId;
    select.append(option);
  }
  // With only one person there is nothing to choose between, so the chooser
  // stays out of the way until someone adds a second.
  select.hidden = people.length < 2;
  $("personName").value = currentPerson()?.name || "";
  $("removePerson").disabled = people.length < 2;
}

async function renderLibrary() {
  if (storeBroken) return;
  const stored = personId ? await getPerson(personId) : null;
  const has = Boolean(stored?.library);
  $("libraryCard").hidden = !has;
  if (!has) {
    updateMergeButton();
    return;
  }

  $("libraryUpdated").textContent = `updated ${shortDate(stored.updated)}`;

  const stats = $("librarySummary");
  stats.replaceChildren();
  for (const [table, label] of HEADLINE) {
    const n = stored.summary?.[table];
    if (!n) continue;
    const box = document.createElement("div");
    box.className = "stat";
    const b = document.createElement("b");
    b.textContent = n.toLocaleString();
    box.append(b, document.createTextNode(label));
    stats.append(box);
  }

  const list = $("devices");
  list.replaceChildren();
  for (const device of stored.devices || []) {
    const li = document.createElement("li");
    li.className = "item";
    const box = document.createElement("div");
    box.className = "grow";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = device.name || "unnamed device";
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `last backup ${shortDate(device.lastModified)}`;
    box.append(name, meta);
    li.append(box);
    list.append(li);
  }

  updateMergeButton();
}

/** The privacy line promises offline use; only promise what is actually true. */
function setPrivacyLine(worksOffline) {
  const offline =
    worksOffline || location.protocol === "file:" || window.BRAID_WASM_BASE64;
  $("privacy").textContent =
    "Nothing is uploaded. Everything happens on this device" +
    (offline ? ", and this page works with no internet." : ".");
}

async function showStorageNote() {
  if (storeBroken) return;
  const persisted = await requestPersistence();
  const room = await usage();
  const parts = [];
  if (room && room.available) {
    parts.push(
      `Remembering uses ${megabytes(room.used)} of the ` +
        `${megabytes(room.available)} this browser allows.`
    );
  }
  parts.push(
    persisted
      ? "This browser has agreed to keep it."
      : "The browser may clear it if the device runs low on space, so keep the" +
          " combined file saved in Files as well."
  );
  $("storageNote").textContent = parts.join(" ");
}

// -- picked files ----------------------------------------------------------

function renderFiles() {
  const list = $("files");
  list.replaceChildren();

  for (const [index, backup] of added.entries()) {
    const li = document.createElement("li");
    li.className = "item";

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
      added.splice(index, 1);
      renderFiles();
    });

    li.append(box, drop);
    list.append(li);
  }

  $("empty").hidden = added.length > 0;
  updateMergeButton();
}

/** How many real devices the library now draws on, ignoring the store itself. */
async function storedDeviceCount(justAdded) {
  const names = new Set(justAdded.map((b) => b.deviceName || b.file.name));
  if (!storeBroken && personId) {
    const stored = await getPerson(personId);
    for (const device of stored?.devices || []) names.add(device.name);
  }
  return names.size;
}

async function hasStoredLibrary() {
  if (storeBroken || !personId) return false;
  const stored = await getPerson(personId);
  return Boolean(stored?.library);
}

/** Whether there is enough on hand to combine anything. */
async function canCombine() {
  // One new backup is enough when there is already a library to add it to.
  return added.length >= ((await hasStoredLibrary()) ? 1 : 2);
}

async function updateMergeButton() {
  const stored = await hasStoredLibrary();
  const enough = added.length >= (stored ? 1 : 2);
  $("merge").disabled = !enough;
  // Combining starts by itself when a backup is added, so this button is only
  // a way back in if that did not happen -- it stays hidden otherwise.
  $("merge").hidden = !enough;

  $("choose").textContent = added.length
    ? "Add another backup"
    : stored
      ? "Add the new backup"
      : "Choose a backup";
}

async function addFiles(fileList) {
  const problems = [];
  for (const file of fileList) {
    if (added.some((b) => b.file.name === file.name && b.file.size === file.size)) {
      continue;
    }
    try {
      added.push(await BackupFile.open(file));
    } catch (error) {
      problems.push(`${file.name}: ${error.message}`);
    }
  }
  renderFiles();
  if (problems.length) {
    say("err", "Some files could not be opened.", problems.join(" "));
    return;
  }

  // Combine straight away rather than making someone find a second button.
  // This only ever writes a new file; the backups that went in are untouched,
  // so there is nothing to undo if it was not what they meant.
  //
  // The decision is computed rather than read off the button, whose state is
  // updated asynchronously and would still say "not yet" at this point.
  if (await canCombine()) await doMerge();
}

// -- the report ------------------------------------------------------------

function reportText(report, check) {
  const lines = [`Started from : ${report.base} (${report.baseDevice})`];
  for (const source of report.sources) {
    lines.push("", `Added from   : ${source.name} (${source.device})`);
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

  lines.push("", "In the combined library");
  for (const table of Object.keys(report.totalsAfter).sort()) {
    const before = report.totalsBefore[table] ?? 0;
    const after = report.totalsAfter[table];
    if (!after) continue;
    const gained = after - before;
    lines.push(
      `  ${table.padEnd(34)}${String(after).padStart(7)}${gained ? `  (+${gained})` : ""}`
    );
  }

  lines.push("", "Checked and found in the combined library");
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

// -- the merge -------------------------------------------------------------

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

    // The remembered library joins the merge as one more input; because the
    // merge only ever adds, folding it back in is what accumulates history.
    const inputs = [...added];
    const stored = storeBroken || !personId ? null : await getPerson(personId);
    if (stored?.library) {
      const file = new File([stored.library], stored.libraryName || "remembered.jwlibrary");
      inputs.push(await BackupFile.open(file));
    }
    if (inputs.length < 2) {
      throw new Error("add at least two backups, or one if a library is remembered");
    }

    // The most recently made backup becomes the starting point.
    const ordered = [...inputs].sort((a, b) =>
      a.lastModified < b.lastModified ? 1 : -1
    );
    const [base, ...sources] = ordered;

    const db = new engine.Database(await base.databaseBytes());
    const mediaPlan = new Map();
    for (const entry of base.mediaEntries()) {
      mediaPlan.set(base.memberName(entry), { backup: base, entry });
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
        db: new engine.Database(await backup.databaseBytes()),
      });
    }
    const check = verify(db, checkSources, new Set(mediaPlan.keys()));
    for (const source of checkSources) source.db.close();

    progressText.textContent = "Writing the combined file…";
    const manifest = JSON.parse(JSON.stringify(base.manifest));
    const stamp = new Date().toISOString().slice(0, 10);
    const name = `Combined library ${stamp}.jwlibrary`;
    manifest.name = name;
    manifest.creationDate = new Date().toISOString();
    manifest.userDataBackup.deviceName = "braid combined";
    manifest.userDataBackup.hash = "";

    const builder = new ZipBuilder();
    await builder.add("manifest.json", new TextEncoder().encode(JSON.stringify(manifest)));
    await builder.add(base.dbEntry.name, db.export());
    for (const [member, { backup, entry }] of mediaPlan) {
      builder.copyFrom(member, entry, await rawSlice(backup.file, entry));
    }
    db.close();

    merged = { blob: builder.finish("application/octet-stream"), name };

    $("report").textContent = reportText(report, check);
    const clean = check.ok && !report.integrityErrors.length;

    // Only remember a result that checked out.
    let remembered = false;
    let storeMessage = "";
    if (clean && !storeBroken && personId) {
      progressText.textContent = "Remembering it for next time…";
      try {
        await rememberLibrary(personId, {
          blob: merged.blob,
          name,
          summary: report.totalsAfter,
          devices: added.map((b) => ({
            name: b.deviceName || b.file.name,
            lastModified: b.lastModified,
          })),
        });
        remembered = true;
      } catch (error) {
        storeMessage = ` It could not be remembered for next time: ${error.message}`;
      }
    }

    if (clean) {
      // Count real devices, not the remembered library that joined the merge.
      const contributing = await storedDeviceCount(added);
      say(
        "ok",
        "Done — everything is there.",
        `Every note, highlight, bookmark, tag and playlist from ${contributing}` +
          ` device${contributing === 1 ? "" : "s"} is in the combined file` +
          ` (${megabytes(merged.blob.size)}).` +
          (remembered ? " It is remembered, so next time add only what changed." : "") +
          storeMessage,
        { showSave: true }
      );
    } else {
      const problems = report.integrityErrors.length + check.missing.length;
      say(
        "warn",
        "Combined, but the check found problems.",
        `${problems} item(s) could not be confirmed, so this was not remembered.` +
          ` Open "What changed" below before you restore this anywhere.`,
        { showSave: true }
      );
    }

    added = [];
    renderFiles();
    await renderLibrary();
    await showStorageNote();
  } catch (error) {
    merged = null;
    $("report").textContent = "";
    say("err", "It did not work.", error.message);
  } finally {
    progress.hidden = true;
    progressText.hidden = true;
    updateMergeButton();
  }
}

// -- saving ----------------------------------------------------------------

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

// -- wiring ----------------------------------------------------------------

$("choose").addEventListener("click", () => $("picker").click());
$("picker").addEventListener("change", async (event) => {
  await addFiles(event.target.files);
  event.target.value = "";
});
$("merge").addEventListener("click", doMerge);

$("save").addEventListener("click", () => {
  if (merged) download(merged.blob, merged.name);
});

$("saveStored").addEventListener("click", async () => {
  const stored = await getPerson(personId);
  if (stored?.library) {
    download(stored.library, stored.libraryName || "Combined library.jwlibrary");
  }
});

$("forget").addEventListener("click", async () => {
  const person = currentPerson();
  if (
    !confirm(
      `Forget the remembered library for ${person?.name || "this person"}?` +
        " Your device backups and any file you have saved are untouched," +
        " but next time you will have to add a backup from every device again."
    )
  ) {
    return;
  }
  await forgetLibrary(personId);
  await renderLibrary();
  await showStorageNote();
});

$("person").addEventListener("change", async (event) => {
  personId = event.target.value;
  rememberCurrentPerson(personId);
  added = [];
  merged = null;
  $("result").hidden = true;
  renderPeople();
  renderFiles();
  await renderLibrary();
});

$("personName").addEventListener("change", async (event) => {
  const name = event.target.value.trim();
  if (!name || !personId) return;
  await renamePerson(personId, name);
  people = await listPeople();
  renderPeople();
});

$("addPerson").addEventListener("click", async () => {
  const name = prompt("Whose library is this?", "");
  if (name === null) return;
  const person = await createPerson(name || "Someone");
  people = await listPeople();
  personId = person.id;
  rememberCurrentPerson(personId);
  added = [];
  merged = null;
  $("result").hidden = true;
  renderPeople();
  renderFiles();
  await renderLibrary();
});

$("removePerson").addEventListener("click", async () => {
  const person = currentPerson();
  if (people.length < 2 || !person) return;
  if (
    !confirm(
      `Remove ${person.name} and the library remembered for them?` +
        " Their device backups and any saved file are untouched."
    )
  ) {
    return;
  }
  await deletePerson(person.id);
  people = await listPeople();
  personId = people[0]?.id || null;
  rememberCurrentPerson(personId);
  renderPeople();
  await renderLibrary();
});

/**
 * Offer to keep the page on the home screen, where it behaves like an app.
 *
 * Whether it also works offline depends on the service worker having
 * registered, so that half of the sentence is only said when it is true.
 */
function showInstallHint(worksOffline) {
  const standalone =
    window.matchMedia?.("(display-mode: standalone)").matches ||
    window.navigator.standalone === true;
  if (standalone || location.protocol === "file:") return;

  const iOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const how = iOS
    ? "tap the Share button, then Add to Home Screen"
    : "install it from your browser's menu";
  $("installHint").textContent =
    `Keep this handy: ${how}. It then opens like an app` +
    (worksOffline ? " and works without internet." : ".");
  $("installHint").hidden = false;
}

/**
 * Cache the page so it opens with no network.
 *
 * Returns whether it worked. Some browsers refuse outright, and offline use is
 * a convenience rather than a requirement, so a refusal changes what the page
 * claims instead of interrupting anyone.
 */
async function registerWorker() {
  if (!("serviceWorker" in navigator)) return false;
  if (location.protocol === "file:") return false; // one local file, nothing to cache
  try {
    await navigator.serviceWorker.register("./sw.js");
    return true;
  } catch {
    return false;
  }
}

(async () => {
  await loadPeople();
  renderFiles();
  await renderLibrary();
  await showStorageNote();
  const worksOffline = await registerWorker();
  setPrivacyLine(worksOffline);
  showInstallHint(worksOffline);
})();
