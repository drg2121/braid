// Tests for what the page remembers between visits.
//
// Run with: node --test web/
//
// fake-indexeddb stands in for the browser's storage. The point of these tests
// is the behaviour people depend on: a library that survives a reload, several
// people who never see each other's data, and a device list that accumulates
// rather than being overwritten by whichever backup was added last.

import "fake-indexeddb/auto";
import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

const store = await import("./store.js");

async function wipe() {
  store.resetConnection();
  await new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase("braid");
    request.onsuccess = resolve;
    request.onerror = () => reject(request.error);
    request.onblocked = resolve;
  });
  try {
    localStorage.clear();
  } catch {
    // No localStorage in this runtime is fine; the store falls back quietly.
  }
}

const summary = { UserMark: 4924, Note: 33, Tag: 12, PlaylistItem: 78 };

function library(text = "a combined library") {
  return new Blob([text], { type: "application/octet-stream" });
}

describe("people", () => {
  beforeEach(wipe);

  it("starts with nobody", async () => {
    assert.deepEqual(await store.listPeople(), []);
  });

  it("creates a person with no library yet", async () => {
    const person = await store.createPerson("Cosmin");
    assert.equal(person.name, "Cosmin");
    assert.equal(person.hasLibrary, false);
    assert.deepEqual(person.devices, []);

    const listed = await store.listPeople();
    assert.equal(listed.length, 1);
    assert.equal(listed[0].name, "Cosmin");
  });

  it("falls back to a name when given a blank one", async () => {
    const person = await store.createPerson("   ");
    assert.equal(person.name, "Me");
  });

  it("renames without touching the library", async () => {
    const person = await store.createPerson("Cosmin");
    await store.rememberLibrary(person.id, {
      blob: library(),
      name: "combined.jwlibrary",
      summary,
      devices: [{ name: "iPhone", lastModified: "2026-08-29T00:00:00Z" }],
    });

    await store.renamePerson(person.id, "Cosmin D");
    const stored = await store.getPerson(person.id);
    assert.equal(stored.name, "Cosmin D");
    assert.ok(stored.library, "the library should survive a rename");
    assert.equal(stored.devices.length, 1);
  });

  it("keeps each person's library separate", async () => {
    const a = await store.createPerson("Cosmin");
    const b = await store.createPerson("Maria");

    await store.rememberLibrary(a.id, {
      blob: library("cosmin"),
      name: "a.jwlibrary",
      summary,
      devices: [{ name: "iPhone", lastModified: "2026-08-29T00:00:00Z" }],
    });
    await store.rememberLibrary(b.id, {
      blob: library("maria"),
      name: "b.jwlibrary",
      summary: { UserMark: 1 },
      devices: [{ name: "iPad", lastModified: "2026-08-01T00:00:00Z" }],
    });

    const storedA = await store.getPerson(a.id);
    const storedB = await store.getPerson(b.id);
    assert.equal(await storedA.library.text(), "cosmin");
    assert.equal(await storedB.library.text(), "maria");
    assert.deepEqual(
      storedA.devices.map((d) => d.name),
      ["iPhone"]
    );
    assert.deepEqual(
      storedB.devices.map((d) => d.name),
      ["iPad"]
    );
    assert.equal(storedB.summary.UserMark, 1);
  });

  it("removing one person leaves the others alone", async () => {
    const a = await store.createPerson("Cosmin");
    const b = await store.createPerson("Maria");
    await store.rememberLibrary(b.id, {
      blob: library("maria"),
      name: "b.jwlibrary",
      summary,
      devices: [{ name: "iPad", lastModified: "2026-08-01T00:00:00Z" }],
    });

    await store.deletePerson(a.id);
    const listed = await store.listPeople();
    assert.equal(listed.length, 1);
    assert.equal(listed[0].name, "Maria");
    assert.ok((await store.getPerson(b.id)).library);
  });

  it("lists the most recently used person first", async () => {
    const a = await store.createPerson("First");
    await new Promise((r) => setTimeout(r, 5));
    await store.createPerson("Second");
    await new Promise((r) => setTimeout(r, 5));
    await store.renamePerson(a.id, "First again");

    const listed = await store.listPeople();
    assert.equal(listed[0].name, "First again");
  });
});

describe("the remembered library", () => {
  beforeEach(wipe);

  it("survives being read back", async () => {
    const person = await store.createPerson("Cosmin");
    await store.rememberLibrary(person.id, {
      blob: library("the whole library"),
      name: "JW Library COMBINED.jwlibrary",
      summary,
      devices: [{ name: "iPhone", lastModified: "2026-08-29T00:00:00Z" }],
    });

    store.resetConnection(); // as if the page had been reloaded
    const stored = await store.getPerson(person.id);
    assert.equal(await stored.library.text(), "the whole library");
    assert.equal(stored.libraryName, "JW Library COMBINED.jwlibrary");
    assert.equal(stored.summary.UserMark, 4924);
  });

  it("accumulates devices instead of replacing them", async () => {
    const person = await store.createPerson("Cosmin");
    await store.rememberLibrary(person.id, {
      blob: library(),
      name: "a",
      summary,
      devices: [
        { name: "iPhone", lastModified: "2026-08-29T00:00:00Z" },
        { name: "iPad", lastModified: "2026-08-04T00:00:00Z" },
      ],
    });

    // A later round adds only the device that changed.
    const devices = await store.rememberLibrary(person.id, {
      blob: library(),
      name: "b",
      summary,
      devices: [{ name: "Laptop", lastModified: "2026-09-01T00:00:00Z" }],
    });

    assert.deepEqual(
      devices.map((d) => d.name),
      ["iPad", "iPhone", "Laptop"]
    );
  });

  it("moves a device's date forward but never backward", async () => {
    const person = await store.createPerson("Cosmin");
    await store.rememberLibrary(person.id, {
      blob: library(),
      name: "a",
      summary,
      devices: [{ name: "iPhone", lastModified: "2026-08-29T00:00:00Z" }],
    });

    // Someone re-adds an older backup from the same device.
    let devices = await store.rememberLibrary(person.id, {
      blob: library(),
      name: "b",
      summary,
      devices: [{ name: "iPhone", lastModified: "2026-01-01T00:00:00Z" }],
    });
    assert.equal(devices[0].lastModified, "2026-08-29T00:00:00Z");

    // And then a genuinely newer one.
    devices = await store.rememberLibrary(person.id, {
      blob: library(),
      name: "c",
      summary,
      devices: [{ name: "iPhone", lastModified: "2026-09-15T00:00:00Z" }],
    });
    assert.equal(devices[0].lastModified, "2026-09-15T00:00:00Z");
  });

  it("replaces the stored library each time rather than piling copies up", async () => {
    const person = await store.createPerson("Cosmin");
    for (const text of ["first", "second", "third"]) {
      await store.rememberLibrary(person.id, {
        blob: library(text),
        name: `${text}.jwlibrary`,
        summary,
        devices: [{ name: "iPhone", lastModified: "2026-08-29T00:00:00Z" }],
      });
    }
    const stored = await store.getPerson(person.id);
    assert.equal(await stored.library.text(), "third");
    assert.equal(stored.devices.length, 1);
  });

  it("forgetting drops the library but keeps the person and their devices", async () => {
    const person = await store.createPerson("Cosmin");
    await store.rememberLibrary(person.id, {
      blob: library(),
      name: "a",
      summary,
      devices: [{ name: "iPhone", lastModified: "2026-08-29T00:00:00Z" }],
    });

    await store.forgetLibrary(person.id);
    const stored = await store.getPerson(person.id);
    assert.equal(stored.library, null);
    assert.deepEqual(stored.summary, {});
    assert.deepEqual(
      stored.devices.map((d) => d.name),
      ["iPhone"],
      "which devices someone has is still worth knowing"
    );
  });

  it("refuses to remember for someone who is no longer stored", async () => {
    const person = await store.createPerson("Cosmin");
    await store.deletePerson(person.id);
    await assert.rejects(
      () =>
        store.rememberLibrary(person.id, {
          blob: library(),
          name: "a",
          summary,
          devices: [],
        }),
      store.StoreError
    );
  });

  it("does not hand the blob back in listings", async () => {
    const person = await store.createPerson("Cosmin");
    await store.rememberLibrary(person.id, {
      blob: library(),
      name: "a",
      summary,
      devices: [{ name: "iPhone", lastModified: "2026-08-29T00:00:00Z" }],
    });

    const listed = await store.listPeople();
    assert.equal(listed[0].library, undefined, "listings must stay small");
    assert.equal(listed[0].hasLibrary, true);
  });
});

describe("which person was last in use", () => {
  beforeEach(wipe);

  it("is remembered and can be cleared", () => {
    // Node has no localStorage unless it is enabled explicitly, so stand one
    // up for the duration of this test.
    const saved = globalThis.localStorage;
    const values = new Map();
    globalThis.localStorage = {
      getItem: (k) => (values.has(k) ? values.get(k) : null),
      setItem: (k, v) => values.set(k, String(v)),
      removeItem: (k) => values.delete(k),
      clear: () => values.clear(),
    };
    try {
      store.rememberCurrentPerson("abc");
      assert.equal(store.currentPersonId(), "abc");
      store.rememberCurrentPerson(null);
      assert.equal(store.currentPersonId(), null);
    } finally {
      globalThis.localStorage = saved;
    }
  });

  it("degrades quietly where the browser blocks storage", () => {
    const saved = globalThis.localStorage;
    globalThis.localStorage = {
      getItem() {
        throw new Error("blocked");
      },
      setItem() {
        throw new Error("blocked");
      },
      removeItem() {
        throw new Error("blocked");
      },
    };
    try {
      // A private window must not break the page; it just forgets.
      assert.doesNotThrow(() => store.rememberCurrentPerson("abc"));
      assert.equal(store.currentPersonId(), null);
    } finally {
      globalThis.localStorage = saved;
    }
  });
});
