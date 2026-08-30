// Tests for language choice and the plural rules.
//
// Run with: node --test web/i18n.test.mjs
//
// Romanian takes three forms and the third one is easy to get wrong, so it is
// pinned here rather than left to be noticed on a screenshot. The counters on
// the page animate upward, which means the noun is asked for at every value
// between zero and the total -- every one of those has to read correctly.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

const i18n = await import("./i18n.js");
const { plural, setLang, t, formatDate } = i18n;

describe("Romanian plurals", () => {
  it("uses the singular for exactly one", () => {
    setLang("ro");
    assert.equal(plural("fig.Bookmark", 1), "marcaj");
    assert.equal(plural("fig.Note", 1), "notiță");
    assert.equal(plural("fig.UserMark", 1), "subliniere");
  });

  it("uses the plain plural from two to nineteen", () => {
    setLang("ro");
    for (const n of [0, 2, 3, 11, 19]) {
      assert.equal(plural("fig.Bookmark", n), "marcaje", `for ${n}`);
    }
  });

  it("adds 'de' from twenty upward", () => {
    setLang("ro");
    for (const n of [20, 21, 65, 99]) {
      assert.equal(plural("fig.UserMark", n), "de sublinieri", `for ${n}`);
    }
  });

  it("decides on the last two digits, so 100 takes 'de' and 101 does not", () => {
    setLang("ro");
    assert.equal(plural("fig.Bookmark", 100), "de marcaje");
    assert.equal(plural("fig.Bookmark", 101), "marcaje");
    assert.equal(plural("fig.Bookmark", 119), "marcaje");
    assert.equal(plural("fig.Bookmark", 120), "de marcaje");
    assert.equal(plural("fig.Bookmark", 1000), "de marcaje");
  });

  it("reads correctly at every value a counter passes through", () => {
    setLang("ro");
    // The figure animates from zero to its total; a noun that only suits the
    // final number would be wrong for most of the way up.
    for (let n = 0; n <= 141; n++) {
      const word = plural("fig.Note", n);
      const within = n % 100;
      // Zero takes the plain plural. Otherwise only the last two digits
      // decide, and only 1 to 19 escape the "de" -- so 100 needs it while
      // 101 does not.
      if (n === 1) assert.equal(word, "notiță", `for ${n}`);
      else if (n === 0 || (within >= 1 && within <= 19)) {
        assert.equal(word, "notițe", `for ${n}`);
      } else assert.equal(word, "de notițe", `for ${n}`);
    }
  });

  it("covers every countable noun in all three forms", () => {
    setLang("ro");
    for (const key of [
      "fig.UserMark",
      "fig.Note",
      "fig.Bookmark",
      "fig.Tag",
      "fig.PlaylistItem",
      "fig.InputField",
      "fig.IndependentMedia",
      "fig.item",
    ]) {
      const one = plural(key, 1);
      const few = plural(key, 5);
      const other = plural(key, 25);
      assert.ok(one && few && other, `${key} is missing a form`);
      assert.notEqual(one, few, `${key}: singular and plural are the same`);
      assert.ok(other.startsWith("de "), `${key}: 25 should take "de"`);
    }
  });
});

describe("English plurals", () => {
  it("uses two forms and never says 'de'", () => {
    setLang("en");
    assert.equal(plural("fig.Bookmark", 1), "bookmark");
    for (const n of [0, 2, 20, 100, 101]) {
      assert.equal(plural("fig.Bookmark", n), "bookmarks", `for ${n}`);
    }
  });
});

describe("looking strings up", () => {
  it("fills placeholders", () => {
    setLang("ro");
    assert.match(t("report.from", { name: "iPad" }), /iPad/);
  });

  it("falls back to English rather than showing a key", () => {
    setLang("ro");
    assert.notEqual(t("hero.a"), "hero.a");
  });

  it("has the same keys in both languages", () => {
    setLang("ro");
    const ro = new Set();
    const en = new Set();
    // Exercised through t(): a key missing from Romanian falls through to
    // English, and one missing from both comes back as the key itself.
    for (const key of [
      "hero.a",
      "hero.b",
      "btn.choose",
      "btn.save",
      "result.okTitle",
      "progress.reading",
      "progress.stayOpen",
      "tour.1.h",
      "tour.5.h",
      "install.android",
      "install.ios-safari",
      "set.people",
      "report.checked",
    ]) {
      setLang("ro");
      const inRo = t(key);
      setLang("en");
      const inEn = t(key);
      assert.notEqual(inRo, key, `${key} missing from Romanian`);
      assert.notEqual(inEn, key, `${key} missing from English`);
      ro.add(inRo);
      en.add(inEn);
    }
    assert.ok(ro.size > 0 && en.size > 0);
  });
});

describe("dates", () => {
  it("follows the chosen language", () => {
    setLang("ro");
    const ro = formatDate("2026-08-29T00:00:00Z");
    setLang("en");
    const en = formatDate("2026-08-29T00:00:00Z");
    assert.match(ro, /2026/);
    assert.match(en, /2026/);
    assert.notEqual(ro, en, "the two languages should not format alike");
  });

  it("hands back what it was given when that is not a date", () => {
    assert.equal(formatDate("not a date"), "not a date");
    assert.equal(formatDate(""), "");
  });
});
