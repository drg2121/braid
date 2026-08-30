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
    "tour.5.h": "Ține-o la îndemână",
    "install.ios-safari": "Apasă butonul de Distribuire din bara de jos, derulează și alege „Adaugă pe ecranul principal”.",
    "install.ios-chrome": "Apasă butonul de Distribuire din dreapta sus, derulează și alege „Adaugă pe ecranul principal”.",
    "install.ios-other": "Browserul acesta nu poate adăuga pagini pe ecranul principal. Deschide adresa în Safari și încearcă acolo.",
    "install.android": "Apasă cele trei puncte din dreapta sus și alege „Instalează aplicația” sau „Adaugă pe ecranul principal”.",
    "install.desktop-safari": "Din meniul Fișier, alege „Adaugă în Dock”.",
    "install.desktop": "Apasă pictograma de instalare din bara de adrese, sau caută „Instalează” în meniul browserului.",
    "install.after": "Apoi se deschide ca o aplicație și merge și fără internet.",
    "install.link": "Cum o pun pe ecran?",
    "tour.open": "Arată-mi cum",
    "tour.skip": "Sari peste",
    "tour.next": "Mai departe",
    "tour.done": "Am înțeles",
    "tour.back": "Înapoi",
    "tour.1.h": "Fă o copie pe fiecare dispozitiv",
    "tour.1.p": "În JW Library, deschide Studiu personal și apasă ⤒ din colțul de sus. Alege să creezi o copie de rezervă și salveaz-o în Fișiere.",
    "tour.2.h": "Adu copiile aici",
    "tour.2.p": "Apasă butonul mare și alege-le. Se combină singure într-o bibliotecă cu tot ce ai pe fiecare dispozitiv.",
    "tour.3.h": "Pune biblioteca la loc",
    "tour.3.p": "Salvează fișierul combinat, apoi pe fiecare dispozitiv alege să restaurezi copia de rezervă. Prima dată durează câteva minute.",
    "tour.4.h": "Data viitoare e mai scurt",
    "tour.4.p": "Biblioteca rămâne aici, deci aduci doar copia de pe dispozitivul pe care ai lucrat. Restul le știe deja.",
    "fig.UserMark": ["subliniere", "sublinieri", "de sublinieri"],
    "fig.Note": ["notiță", "notițe", "de notițe"],
    "fig.Bookmark": ["marcaj", "marcaje", "de marcaje"],
    "fig.Tag": ["etichetă", "etichete", "de etichete"],
    "fig.PlaylistItem": ["element playlist", "elemente playlist", "de elemente playlist"],
    "fig.InputField": ["răspuns de studiu", "răspunsuri de studiu", "de răspunsuri de studiu"],
    "fig.IndependentMedia": ["fișier media", "fișiere media", "de fișiere media"],
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
    "btn.addPerson": "Adaugă o persoană",
    "btn.remove": "Șterge persoana",
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
    "result.badFiles": "Unele fișiere nu au putut fi folosite.",
    "err.notBackup": "„{name}” nu este o copie de rezervă JW Library. Alege fișierul salvat din Personal Study ▸ ⤒.",

    "progress.reading": "Se citesc copiile…",
    "progress.merging": "Se combină {name}",
    "progress.checking": "Se verifică să nu se fi pierdut nimic…",
    "progress.writing": "Se scrie fișierul combinat…",
    "progress.remembering": "Se păstrează pentru data viitoare…",

    "report.from": "De pe {name}",
    "report.nothingNew": "Nimic nou — era deja tot aici.",
    "report.checked": "Verificat",
    "report.checkedBody": "Toate cele {n} {items} din copiile adăugate se regăsesc în fișierul combinat.",
    "fig.item": ["element", "elemente", "de elemente"],
    "report.worth": "De știut",
    "report.technical": "Detalii tehnice",

    "warn.restore": "Restaurarea înlocuiește",
    "warn.restoreRest": " biblioteca de pe acel dispozitiv cu cea combinată. Păstrează copiile originale până verifici.",

    "set.title": "Setări",
    "set.answers": "Dacă un răspuns de studiu diferă",
    "set.keep": "Cea mai nouă",
    "set.overwrite": "Celălalt dispozitiv",
    "set.people": "Mai multe persoane",
    "set.peopleWhy": "Dacă telefonul acesta e folosit și de altcineva, poate avea biblioteca lui, separată de a ta. Dacă ești singurul care îl folosește, lasă cum e.",
    "set.whose": "Numele tău",
    "set.language": "Limbă",
    "set.theme": "Aspect",
    "theme.auto": "Automat",
    "theme.light": "Luminos",
    "theme.dark": "Întunecat",

    "storage.usage": "Ocupă {used} din {available} permis de browser.",
    "storage.kept": "Browserul a acceptat să le păstreze.",
    "storage.mayClear": "Browserul le poate șterge dacă rămâne fără spațiu, deci salvează și fișierul.",
    "storage.broken": "Browserul nu poate păstra nimic ({reason}), deci va trebui să adaugi copii de pe fiecare dispozitiv de fiecare dată. Combinarea funcționează în continuare.",


    "confirm.forget": "Uiți biblioteca păstrată pentru {name}? Copiile de pe dispozitive și fișierele salvate rămân neatinse.",
    "confirm.removePerson": "Ștergi {name} și biblioteca păstrată pentru el? Copiile de pe dispozitive rămân neatinse.",
    "prompt.newPerson": "Cum o cheamă persoana care va avea propria bibliotecă?",
    "person.default": "Eu",
    "person.someone": "Cineva",

    "err.needTwo": "adaugă cel puțin două copii, sau una dacă există deja o bibliotecă păstrată",
    "err.schema": "{file} folosește versiunea de schemă {a}, iar {base} folosește {b}. Actualizează JW Library pe ambele dispozitive și fă copiile din nou.",
  },

  en: {
    "tour.5.h": "Keep it to hand",
    "install.ios-safari": "Tap the Share button in the bottom bar, scroll down, and choose Add to Home Screen.",
    "install.ios-chrome": "Tap the Share button at the top right, scroll down, and choose Add to Home Screen.",
    "install.ios-other": "This browser cannot add pages to the home screen. Open the address in Safari and try there.",
    "install.android": "Tap the three dots at the top right and choose Install app, or Add to Home screen.",
    "install.desktop-safari": "From the File menu, choose Add to Dock.",
    "install.desktop": "Click the install icon in the address bar, or look for Install in your browser's menu.",
    "install.after": "It then opens like an app and works with no internet.",
    "install.link": "How do I put it on my screen?",
    "tour.open": "Show me how",
    "tour.skip": "Skip",
    "tour.next": "Next",
    "tour.done": "Got it",
    "tour.back": "Back",
    "tour.1.h": "Make a backup on each device",
    "tour.1.p": "In JW Library, open Personal Study and tap ⤒ at the top. Choose to create a backup, and save it to Files.",
    "tour.2.h": "Bring them here",
    "tour.2.p": "Tap the big button and pick them. They combine on their own into one library holding everything from every device.",
    "tour.3.h": "Put the library back",
    "tour.3.p": "Save the combined file, then on each device choose to restore the backup. The first round takes a few minutes.",
    "tour.4.h": "Next time is shorter",
    "tour.4.p": "The library stays here, so you only bring the backup from the device you actually used. It already knows the rest.",
    "fig.UserMark": ["highlight", "highlights"],
    "fig.Note": ["note", "notes"],
    "fig.Bookmark": ["bookmark", "bookmarks"],
    "fig.Tag": ["tag", "tags"],
    "fig.PlaylistItem": ["playlist item", "playlist items"],
    "fig.InputField": ["study answer", "study answers"],
    "fig.IndependentMedia": ["media file", "media files"],
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
    "btn.addPerson": "Add a person",
    "btn.remove": "Remove person",
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
    "result.badFiles": "Some files could not be used.",
    "err.notBackup": "\u201c{name}\u201d is not a JW Library backup. Choose the file you saved from Personal Study \u25b8 \u2913.",

    "progress.reading": "Reading your backups…",
    "progress.merging": "Merging {name}",
    "progress.checking": "Checking that nothing was lost…",
    "progress.writing": "Writing the combined file…",
    "progress.remembering": "Remembering it for next time…",

    "report.from": "From {name}",
    "report.nothingNew": "Nothing new — it was all here already.",
    "report.checked": "Checked",
    "report.checkedBody": "All {n} {items} from the backups you added are in the combined file.",
    "fig.item": ["item", "items"],
    "report.worth": "Worth knowing",
    "report.technical": "Technical detail",

    "warn.restore": "Restoring replaces",
    "warn.restoreRest": " that device's library with the combined one. Keep your originals until you have checked it.",

    "set.title": "Settings",
    "set.answers": "If a study answer differs",
    "set.keep": "Most recent",
    "set.overwrite": "Other device",
    "set.people": "More than one person",
    "set.peopleWhy": "If someone else uses this phone, they can keep their own library, separate from yours. If you are the only one, leave this alone.",
    "set.whose": "Your name",
    "set.language": "Language",
    "set.theme": "Appearance",
    "theme.auto": "Automatic",
    "theme.light": "Light",
    "theme.dark": "Dark",

    "storage.usage": "Using {used} of the {available} this browser allows.",
    "storage.kept": "This browser has agreed to keep it.",
    "storage.mayClear": "The browser may clear it if the device runs low on space, so keep the file saved too.",
    "storage.broken": "This browser cannot remember anything ({reason}), so you will need to add a backup from every device each time. Combining still works.",


    "confirm.forget": "Forget the library remembered for {name}? Your device backups and any saved file are untouched.",
    "confirm.removePerson": "Remove {name} and the library remembered for them? Their device backups are untouched.",
    "prompt.newPerson": "What is the name of the person who gets their own library?",
    "person.default": "Me",
    "person.someone": "Someone",

    "err.needTwo": "add at least two backups, or one if a library is remembered",
    "err.schema": "{file} uses schema version {a} but {base} uses {b}. Update JW Library on both devices and make the backups again.",
  },
};

/**
 * Romanian for a Romanian phone, English for everything else.
 *
 * Only consulted when nobody has chosen: an explicit pick is remembered and
 * outranks whatever the device says.
 */
function preferredLang() {
  // Only the top preference counts. A phone set to English commonly lists
  // Romanian further down as a fallback, and treating that as a vote for
  // Romanian would hand an English speaker a Romanian page.
  const top = navigator.languages?.[0] || navigator.language || "";
  return String(top).toLowerCase().startsWith("ro") ? "ro" : "en";
}

let lang = read(STORE_LANG, "");
if (!LANGS.includes(lang)) lang = preferredLang();

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
  // Writing it makes the choice stick, so the device is not asked again.
  lang = next;
  write(STORE_LANG, next);
  document.documentElement.lang = next;
}

/**
 * The right noun for a count.
 *
 * Romanian takes three forms, and the third is the one everyone forgets: past
 * nineteen the noun needs "de" in front of it, so 65 is "65 de sublinieri"
 * rather than "65 sublinieri". English needs only singular and plural.
 */
export function plural(key, n) {
  const table = STRINGS[lang] || STRINGS.ro;
  const forms = table[key] || STRINGS.en[key];
  if (!Array.isArray(forms)) return String(forms ?? key);
  if (n === 1) return forms[0];
  if (forms.length < 3) return forms[1];
  // Zero takes the plain plural; otherwise it is the last two digits that
  // decide, and only 1 through 19 escape the "de". So 100 needs it and 101
  // does not.
  const within = Math.abs(n) % 100;
  const few = n === 0 || (within >= 1 && within <= 19);
  return few ? forms[1] : forms[2];
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
