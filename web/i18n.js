// Language and theme, both remembered on the device.
//
// Romanian is the default because that is who this was built for. English is
// there so the page can be handed to anyone else without explanation.

const STORE_LANG = "braid.lang";
const STORE_THEME = "braid.theme";

export const LANGS = ["ro", "en"];
export const THEMES = ["auto", "light", "dark"];

const STRINGS = {
  ro: {
    "hero.a": "Fiecare dispozitiv.",
    "hero.b": "O bibliotecă.",
    "pill.on": "Rămâne pe telefonul tău, cu sau fără internet",
    "pill.off": "Rămâne pe telefonul tău",

    "lbl.library": "Biblioteca ta",
    "lbl.adding": "Se adaugă",
    "lbl.how": "Cum funcționează",
    "lbl.result": "Rezultat",
    "lbl.updated": "actualizată {date}",

    "step": "PASUL {n}",
    "step1.h": "Exportă",
    "step1.p": "În JW Library: Studiu personal, apoi ⤒, apoi creează o copie de rezervă.",
    "step2.h": "Adaugă aici",
    "step2.p": "Combinarea pornește singură și se verifică la final.",
    "step3.h": "Restaurează",
    "step3.p": "Salvează fișierul, apoi restaurează-l pe fiecare dispozitiv.",

    "btn.choose": "Alege o copie",
    "btn.addAnother": "Adaugă altă copie",
    "btn.addNew": "Adaugă noua copie",
    "btn.addShort": "Adaugă",
    "btn.save": "Salvează fișierul",
    "btn.combineNow": "Combină acum",
    "btn.addPerson": "Adaugă pe cineva",
    "btn.remove": "Șterge",
    "btn.saveStored": "Salvează ce e păstrat",
    "btn.forget": "Uită biblioteca",

    "result.then": "Apoi pe fiecare dispozitiv: în JW Library, Studiu personal, ⤒, restaurează copia de rezervă.",
    "result.whatChanged": "Ce s-a schimbat",
    "result.okTitle": "Gata — totul e acolo.",
    "result.okBody": "Fiecare notiță, subliniere, marcaj, etichetă și playlist de pe {n} dispozitive este în fișierul combinat ({size}).",
    "result.remembered": " Este păstrat, deci data viitoare adaugi doar ce s-a schimbat.",
    "result.warnTitle": "Combinat, dar verificarea a găsit probleme.",
    "result.warnBody": "{n} element(e) nu au putut fi confirmate, deci nu s-a păstrat nimic. Deschide „Ce s-a schimbat” înainte să restaurezi.",
    "result.errTitle": "Nu a mers.",
    "result.badFiles": "Unele fișiere nu au putut fi deschise.",

    "progress.reading": "Se citesc copiile…",
    "progress.merging": "Se combină {name}",
    "progress.checking": "Se verifică să nu se fi pierdut nimic…",
    "progress.writing": "Se scrie fișierul combinat…",
    "progress.remembering": "Se păstrează pentru data viitoare…",

    "fig.UserMark": "sublinieri",
    "fig.Note": "notițe",
    "fig.Bookmark": "marcaje",
    "fig.Tag": "etichete",
    "fig.PlaylistItem": "elemente playlist",

    "warn.restore": "Restaurarea înlocuiește",
    "warn.restoreRest": " biblioteca de pe acel dispozitiv cu cea combinată. Păstrează copiile originale până verifici.",

    "set.title": "Setări",
    "set.answers": "Dacă un răspuns de studiu diferă",
    "set.keep": "Păstrează cel mai recent",
    "set.overwrite": "Ia-l pe al celuilalt dispozitiv",
    "set.whose": "A cui bibliotecă",
    "set.language": "Limbă",
    "set.theme": "Aspect",
    "theme.auto": "Automat",
    "theme.light": "Luminos",
    "theme.dark": "Întunecat",

    "storage.usage": "Ocupă {used} din {available} permis de browser.",
    "storage.kept": "Browserul a acceptat să le păstreze.",
    "storage.mayClear": "Browserul le poate șterge dacă rămâne fără spațiu, deci salvează și fișierul.",
    "storage.broken": "Browserul nu poate păstra nimic ({reason}), deci va trebui să adaugi copii de pe fiecare dispozitiv de fiecare dată. Combinarea funcționează în continuare.",

    "install.ios": "Distribuie ▸ Adaugă pe ecranul principal, și se deschide ca o aplicație.",
    "install.other": "Instaleaz-o din meniul browserului, și se deschide ca o aplicație.",

    "confirm.forget": "Uiți biblioteca păstrată pentru {name}? Copiile de pe dispozitive și fișierele salvate rămân neatinse.",
    "confirm.removePerson": "Ștergi {name} și biblioteca păstrată pentru el? Copiile de pe dispozitive rămân neatinse.",
    "prompt.newPerson": "A cui este biblioteca?",
    "person.default": "Eu",
    "person.someone": "Cineva",

    "err.needTwo": "adaugă cel puțin două copii, sau una dacă există deja o bibliotecă păstrată",
    "err.schema": "{file} folosește versiunea de schemă {a}, iar {base} folosește {b}. Actualizează JW Library pe ambele dispozitive și fă copiile din nou.",
  },

  en: {
    "hero.a": "Every device.",
    "hero.b": "One library.",
    "pill.on": "Stays on your phone, online or not",
    "pill.off": "Stays on your phone",

    "lbl.library": "Your library",
    "lbl.adding": "Adding",
    "lbl.how": "How it works",
    "lbl.result": "Result",
    "lbl.updated": "updated {date}",

    "step": "STEP {n}",
    "step1.h": "Export",
    "step1.p": "In JW Library: Personal Study, then ⤒, then create a backup.",
    "step2.h": "Add it here",
    "step2.p": "Combining starts on its own, then checks itself.",
    "step3.h": "Restore",
    "step3.p": "Save the file, then restore it on every device.",

    "btn.choose": "Choose a backup",
    "btn.addAnother": "Add another backup",
    "btn.addNew": "Add the new backup",
    "btn.addShort": "Add more",
    "btn.save": "Save the file",
    "btn.combineNow": "Combine now",
    "btn.addPerson": "Add someone",
    "btn.remove": "Remove",
    "btn.saveStored": "Save stored",
    "btn.forget": "Forget library",

    "result.then": "Then on each device: in JW Library, Personal Study, ⤒, restore the backup.",
    "result.whatChanged": "What changed",
    "result.okTitle": "Done — everything is there.",
    "result.okBody": "Every note, highlight, bookmark, tag and playlist from {n} devices is in the combined file ({size}).",
    "result.remembered": " It is remembered, so next time add only what changed.",
    "result.warnTitle": "Combined, but the check found problems.",
    "result.warnBody": "{n} item(s) could not be confirmed, so nothing was remembered. Open “What changed” before you restore this anywhere.",
    "result.errTitle": "It did not work.",
    "result.badFiles": "Some files could not be opened.",

    "progress.reading": "Reading your backups…",
    "progress.merging": "Merging {name}",
    "progress.checking": "Checking that nothing was lost…",
    "progress.writing": "Writing the combined file…",
    "progress.remembering": "Remembering it for next time…",

    "fig.UserMark": "highlights",
    "fig.Note": "notes",
    "fig.Bookmark": "bookmarks",
    "fig.Tag": "tags",
    "fig.PlaylistItem": "playlist items",

    "warn.restore": "Restoring replaces",
    "warn.restoreRest": " that device's library with the combined one. Keep your originals until you have checked it.",

    "set.title": "Settings",
    "set.answers": "If a study answer differs",
    "set.keep": "Keep the most recent",
    "set.overwrite": "Take the other device's",
    "set.whose": "Whose library",
    "set.language": "Language",
    "set.theme": "Appearance",
    "theme.auto": "Automatic",
    "theme.light": "Light",
    "theme.dark": "Dark",

    "storage.usage": "Using {used} of the {available} this browser allows.",
    "storage.kept": "This browser has agreed to keep it.",
    "storage.mayClear": "The browser may clear it if the device runs low on space, so keep the file saved too.",
    "storage.broken": "This browser cannot remember anything ({reason}), so you will need to add a backup from every device each time. Combining still works.",

    "install.ios": "Share ▸ Add to Home Screen, and it opens like an app.",
    "install.other": "Install it from your browser menu, and it opens like an app.",

    "confirm.forget": "Forget the library remembered for {name}? Your device backups and any saved file are untouched.",
    "confirm.removePerson": "Remove {name} and the library remembered for them? Their device backups are untouched.",
    "prompt.newPerson": "Whose library is this?",
    "person.default": "Me",
    "person.someone": "Someone",

    "err.needTwo": "add at least two backups, or one if a library is remembered",
    "err.schema": "{file} uses schema version {a} but {base} uses {b}. Update JW Library on both devices and make the backups again.",
  },
};

let lang = read(STORE_LANG, "ro");
if (!LANGS.includes(lang)) lang = "ro";

function read(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // A private window simply forgets the choice.
  }
}

export function currentLang() {
  return lang;
}

export function setLang(next) {
  if (!LANGS.includes(next)) return;
  lang = next;
  write(STORE_LANG, next);
  document.documentElement.lang = next;
}

/** Look up a string, filling {placeholders}. */
export function t(key, vars) {
  const table = STRINGS[lang] || STRINGS.ro;
  let text = table[key] ?? STRINGS.en[key] ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.replaceAll(`{${name}}`, String(value));
    }
  }
  return text;
}

/** Fill every element carrying data-i18n. */
export function applyStatic(root = document) {
  for (const el of root.querySelectorAll("[data-i18n]")) {
    const key = el.dataset.i18n;
    const vars = el.dataset.i18nVars ? JSON.parse(el.dataset.i18nVars) : undefined;
    el.textContent = t(key, vars);
  }
  document.documentElement.lang = lang;
}

/** Dates in the reader's own language. */
export function formatDate(iso) {
  if (!iso) return "";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString(lang === "ro" ? "ro-RO" : "en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// ---- appearance ----------------------------------------------------------

let theme = read(STORE_THEME, "auto");
if (!THEMES.includes(theme)) theme = "auto";

export function currentTheme() {
  return theme;
}

export function setTheme(next) {
  if (!THEMES.includes(next)) return;
  theme = next;
  write(STORE_THEME, next);
  applyTheme();
}

/**
 * "auto" leaves the decision to the system, which is what the stylesheet does
 * on its own; the other two pin it with an attribute the stylesheet overrides
 * the media query with.
 */
export function applyTheme() {
  const root = document.documentElement;
  if (theme === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);

  const dark =
    theme === "dark" ||
    (theme === "auto" &&
      window.matchMedia?.("(prefers-color-scheme: dark)").matches);
  for (const meta of document.querySelectorAll('meta[name="theme-color"]')) {
    meta.remove();
  }
  const meta = document.createElement("meta");
  meta.name = "theme-color";
  meta.content = dark ? "#0b0b0d" : "#f7f6f3";
  document.head.append(meta);
}
