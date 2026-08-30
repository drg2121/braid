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
import {
  LANGS,
  THEMES,
  applyStatic,
  applyTheme,
  currentLang,
  currentTheme,
  formatDate,
  setLang,
  setTheme,
  t,
} from "./i18n.js";
import { verify } from "./verify.js";

const $ = (id) => document.getElementById(id);

// Rows worth showing as a headline; the rest stay in the detailed report.
const HEADLINE = ["UserMark", "Note", "Bookmark", "Tag", "PlaylistItem"];

let SQL = null;
let people = [];
let personId = null;
let added = []; // BackupFile objects picked this visit
let merged = null; // { blob, name }
let storeBroken = false;
let offlineReady = false;

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

const shortDate = formatDate;

/**
 * Run a number up to its value.
 *
 * Four thousand highlights arriving instantly reads as a static label; the
 * same number climbing reads as work that was done. Skipped when the reader
 * has asked for less motion, and for small numbers where it would only be
 * fidget.
 */
function countUp(node, value) {
  const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  if (still || value < 20) {
    node.textContent = value.toLocaleString();
    return;
  }
  const duration = 900;
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    // Ease out, so it arrives rather than stopping dead.
    const eased = 1 - Math.pow(1 - t, 3);
    node.textContent = Math.round(value * eased).toLocaleString();
    if (t < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function banner(target, kind, title, detail) {
  target.replaceChildren();
  const box = document.createElement("div");
  box.className = `note ${kind}`;
  const strong = document.createElement("strong");
  strong.textContent = title;
  box.append(strong, document.createTextNode(detail));
  target.append(box);
}

function say(kind, title, detail, { showSave = false, reveal = false } = {}) {
  banner($("resultBanner"), kind, title, detail);
  $("save").hidden = !showSave;
  $("result").hidden = false;
  // On a phone the result is usually below the fold by the time it appears.
  if (reveal) {
    $("result").scrollIntoView({ behavior: "smooth", block: "start" });
  }
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
      t("storage.broken", { reason: error.message });
    return;
  }

  if (!people.length) {
    people = [await createPerson(t("person.default"))];
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
  reveal("libraryCard", has);
  if (!has) {
    updateMergeButton();
    return;
  }

  $("libraryUpdated").textContent = t("lbl.updated", { date: shortDate(stored.updated) });

  const stats = $("librarySummary");
  stats.replaceChildren();
  for (const table of HEADLINE) {
    const label = t(`fig.${table}`);
    const n = stored.summary?.[table];
    if (!n) continue;
    const box = document.createElement("div");
    box.className = "fig";
    const b = document.createElement("b");
    const caption = document.createElement("span");
    caption.textContent = label;
    box.append(b, caption);
    stats.append(box);
    countUp(b, n);
  }

  const list = $("devices");
  list.replaceChildren();
  for (const device of stored.devices || []) {
    const li = document.createElement("li");
    li.className = "row";
    const name = document.createElement("span");
    name.className = "name grow";
    name.textContent = device.name || "unnamed device";
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = shortDate(device.lastModified);
    li.append(name, meta);
    list.append(li);
  }

  updateMergeButton();
}

/** The privacy line promises offline use; only promise what is actually true. */
function setPrivacyLine(worksOffline) {
  const offline =
    worksOffline || location.protocol === "file:" || window.BRAID_WASM_BASE64;
  $("privacy").textContent = offline ? t("pill.on") : t("pill.off");
}

async function showStorageNote() {
  if (storeBroken) return;
  const persisted = await requestPersistence();
  const room = await usage();
  const parts = [];
  if (room && room.available) {
    parts.push(
      t("storage.usage", {
        used: megabytes(room.used),
        available: megabytes(room.available),
      })
    );
  }
  parts.push(persisted ? t("storage.kept") : t("storage.mayClear"));
  $("storageNote").textContent = parts.join(" ");
}

// -- picked files ----------------------------------------------------------

function renderFiles() {
  const list = $("files");
  list.replaceChildren();

  for (const [index, backup] of added.entries()) {
    const li = document.createElement("li");
    li.className = "row";

    const name = document.createElement("span");
    name.className = "name grow";
    name.textContent = backup.deviceName || backup.file.name;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent =
      `${shortDate(backup.lastModified)} · ${megabytes(backup.file.size)}`;

    const drop = document.createElement("button");
    drop.className = "drop";
    drop.type = "button";
    drop.textContent = "×";
    drop.setAttribute("aria-label", `Remove ${backup.file.name}`);
    drop.addEventListener("click", () => {
      added.splice(index, 1);
      renderFiles();
    });

    li.append(name, meta, drop);
    list.append(li);
  }

  reveal("picked", added.length > 0);
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

  // Beside a Save button there is no room for a sentence, so the label
  // shortens rather than wrapping the primary action onto two lines.
  const beside = !$("save").hidden;
  $("choose").textContent = beside
    ? t("btn.addShort")
    : added.length
      ? t("btn.addAnother")
      : stored
        ? t("btn.addNew")
        : t("btn.choose");
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
    say("err", t("result.badFiles"), problems.join(" "));
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
  progressText.textContent = t("progress.reading");
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
      throw new Error(t("err.needTwo"));
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

    progressText.textContent = t("progress.checking");
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

    progressText.textContent = t("progress.writing");
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
      progressText.textContent = t("progress.remembering");
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
        storeMessage = ` ${error.message}`;
      }
    }

    if (clean) {
      // Count real devices, not the remembered library that joined the merge.
      const contributing = await storedDeviceCount(added);
      say(
        "ok",
        t("result.okTitle"),
        t("result.okBody", {
          n: contributing,
          size: megabytes(merged.blob.size),
        }) + (remembered ? t("result.remembered") : "") + storeMessage,
        { showSave: true, reveal: true }
      );
    } else {
      const problems = report.integrityErrors.length + check.missing.length;
      say("warn", t("result.warnTitle"), t("result.warnBody", { n: problems }), {
        showSave: true,
        reveal: true,
      });
    }

    added = [];
    renderFiles();
    await renderLibrary();
    await showStorageNote();
  } catch (error) {
    merged = null;
    $("report").textContent = "";
    say("err", t("result.errTitle"), error.message);
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
    !confirm(t("confirm.forget", { name: person?.name || "" }))
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
  const name = prompt(t("prompt.newPerson"), "");
  if (name === null) return;
  const person = await createPerson(name || t("person.someone"));
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
    !confirm(t("confirm.removePerson", { name: person.name }))
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
  $("installHint").textContent = iOS ? t("install.ios") : t("install.other");
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

/**
 * Reveal a section that JavaScript has just unhidden.
 *
 * A .watch section starts at zero opacity and is normally revealed by the
 * observer below. That never fires for a section that was display:none when
 * the page loaded, because it has no box to intersect -- so anything unhidden
 * later has to be told directly, or it stays invisible forever.
 */
function reveal(id, show) {
  const el = $(id);
  if (!el) return;
  el.hidden = !show;
  if (show) requestAnimationFrame(() => el.classList.add("seen"));
}

/** Sections fade up as they come into view. */
function watchSections() {
  const targets = document.querySelectorAll(".watch");
  if (!("IntersectionObserver" in window)) {
    targets.forEach((el) => el.classList.add("seen"));
    return;
  }
  const seer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("seen");
          seer.unobserve(entry.target);
        }
      }
    },
    { rootMargin: "0px 0px -12% 0px" }
  );
  targets.forEach((el) => seer.observe(el));
}

/** Mark the chosen option in a segmented control. */
function paintSegment(group, value, attr) {
  for (const button of group.querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset[attr] === value));
  }
}

/** Redraw everything that carries words, after the language changes. */
async function retranslate() {
  applyStatic();
  renderPeople();
  renderFiles();
  await renderLibrary();
  await showStorageNote();
  showInstallHint(offlineReady);
  paintSegment($("langSeg"), currentLang(), "lang");
  paintSegment($("themeSeg"), currentTheme(), "themeSet");
}

function wireSettings() {
  $("langSeg").addEventListener("click", async (event) => {
    const choice = event.target.closest("button")?.dataset.lang;
    if (!choice || !LANGS.includes(choice) || choice === currentLang()) return;
    setLang(choice);
    await retranslate();
  });

  $("themeSeg").addEventListener("click", (event) => {
    const choice = event.target.closest("button")?.dataset.themeSet;
    if (!choice || !THEMES.includes(choice)) return;
    setTheme(choice);
    paintSegment($("themeSeg"), choice, "themeSet");
  });

  // With appearance left on automatic, follow the system when it changes.
  window
    .matchMedia?.("(prefers-color-scheme: dark)")
    .addEventListener?.("change", () => {
      if (currentTheme() === "auto") applyTheme();
    });
}

/** The mark is inlined rather than an <img> so currentColor reaches it. */
function drawMark() {
  const source = document.getElementById("markSource");
  const target = $("mark");
  if (source && target) target.append(source.content.cloneNode(true));
}

(async () => {
  applyTheme();
  applyStatic();
  drawMark();
  watchSections();
  wireSettings();
  paintSegment($("langSeg"), currentLang(), "lang");
  paintSegment($("themeSeg"), currentTheme(), "themeSet");

  await loadPeople();
  renderFiles();
  await renderLibrary();
  await showStorageNote();

  offlineReady = await registerWorker();
  setPrivacyLine(offlineReady);
  showInstallHint(offlineReady);
})();
