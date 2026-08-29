// What the page remembers between visits.
//
// The point of remembering is that you should not have to export a backup from
// every device every time. The combined library is kept here, so the next round
// only needs a fresh backup from the device you actually used -- it gets merged
// into what is already stored.
//
// Everything lives in this browser, on this device, in IndexedDB. Nothing is
// sent anywhere, and a person can clear it at any time.
//
// One store can hold several people, because a shared iPad is normal and
// because someone helping others should not mix their libraries together.

const STORAGE_DB_NAME = "braid";
const STORAGE_DB_VERSION = 1;
const PEOPLE_STORE = "people";

export class StoreError extends Error {}

let dbPromise = null;
let openDb = null;

function openDatabase() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (!("indexedDB" in globalThis) || !globalThis.indexedDB) {
      reject(new StoreError("this browser cannot remember anything"));
      return;
    }
    const request = indexedDB.open(STORAGE_DB_NAME, STORAGE_DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(PEOPLE_STORE)) {
        db.createObjectStore(PEOPLE_STORE, { keyPath: "id" });
      }
    };
    request.onsuccess = () => {
      openDb = request.result;
      // Another tab upgrading the schema needs this connection out of the way.
      openDb.onversionchange = () => {
        openDb.close();
        openDb = null;
        dbPromise = null;
      };
      resolve(openDb);
    };
    request.onerror = () =>
      reject(new StoreError(request.error?.message || "could not open storage"));
    request.onblocked = () =>
      reject(new StoreError("another tab has this page open; close it and retry"));
  });
  return dbPromise;
}

function transact(storeName, mode, work) {
  return openDatabase().then(
    (db) =>
      new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, mode);
        const store = tx.objectStore(storeName);
        let result;
        try {
          result = work(store);
        } catch (error) {
          reject(error);
          return;
        }
        // "value" is present as soon as the request succeeded, even when the
        // record was missing and the value is undefined. Testing the value
        // itself would turn "no such person" into an empty object.
        tx.oncomplete = () =>
          resolve(result && "value" in result ? result.value : result);
        tx.onerror = () =>
          reject(new StoreError(tx.error?.message || "storage refused the change"));
        tx.onabort = () =>
          reject(
            new StoreError(
              tx.error?.name === "QuotaExceededError"
                ? "there is not enough room left on this device to remember this library"
                : tx.error?.message || "storage refused the change"
            )
          );
      })
  );
}

function request(store, method, ...args) {
  const req = store[method](...args);
  const box = {};
  req.onsuccess = () => {
    // Assigned even when req.result is undefined, so the caller can tell a
    // missing record apart from a request that never ran.
    box.value = req.result;
  };
  return box;
}

function newId() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  return `p${Date.now()}${Math.random().toString(16).slice(2)}`;
}

/**
 * Ask the browser to keep this data rather than evicting it under pressure.
 * Returns whether it agreed; it is only ever a request.
 */
export async function requestPersistence() {
  try {
    if (navigator.storage?.persisted && (await navigator.storage.persisted())) {
      return true;
    }
    if (navigator.storage?.persist) return await navigator.storage.persist();
  } catch {
    // Storage APIs throw in some private-browsing modes; not being able to ask
    // is not an error worth surfacing.
  }
  return false;
}

/** Roughly how much room the stored libraries take, and how much is left. */
export async function usage() {
  try {
    const estimate = await navigator.storage?.estimate?.();
    if (!estimate) return null;
    return { used: estimate.usage ?? 0, available: estimate.quota ?? 0 };
  } catch {
    return null;
  }
}

/** Everyone this browser is remembering, most recently used first. */
export async function listPeople() {
  const people = await transact(PEOPLE_STORE, "readonly", (store) =>
    request(store, "getAll")
  );
  return (people || [])
    .map(({ library, ...rest }) => ({ ...rest, hasLibrary: Boolean(library) }))
    .sort((a, b) => (a.updated < b.updated ? 1 : -1));
}

export async function createPerson(name) {
  const person = {
    id: newId(),
    name: name.trim() || "Me",
    created: new Date().toISOString(),
    updated: new Date().toISOString(),
    devices: [],
    summary: {},
    library: null,
    libraryName: "",
  };
  await transact(PEOPLE_STORE, "readwrite", (store) => request(store, "put", person));
  const { library, ...rest } = person;
  return { ...rest, hasLibrary: false };
}

export async function renamePerson(id, name) {
  const person = await getPerson(id);
  if (!person) throw new StoreError("that person is no longer stored here");
  person.name = name.trim() || person.name;
  person.updated = new Date().toISOString();
  await transact(PEOPLE_STORE, "readwrite", (store) => request(store, "put", person));
}

export async function deletePerson(id) {
  await transact(PEOPLE_STORE, "readwrite", (store) => request(store, "delete", id));
}

/** The full record, including the stored library blob. */
export async function getPerson(id) {
  return transact(PEOPLE_STORE, "readonly", (store) => request(store, "get", id));
}

/**
 * Store the combined library for a person, along with what is in it and which
 * devices have contributed so far.
 */
export async function rememberLibrary(id, { blob, name, summary, devices }) {
  const person = await getPerson(id);
  if (!person) throw new StoreError("that person is no longer stored here");

  const seen = new Map((person.devices || []).map((d) => [d.name, d]));
  for (const device of devices) {
    const previous = seen.get(device.name);
    // Keep the earliest date this device was ever seen, and the latest backup.
    seen.set(device.name, {
      name: device.name,
      lastModified:
        !previous || previous.lastModified < device.lastModified
          ? device.lastModified
          : previous.lastModified,
      seenAt: new Date().toISOString(),
      firstSeen: previous?.firstSeen || new Date().toISOString(),
    });
  }

  person.devices = [...seen.values()].sort((a, b) =>
    a.name.localeCompare(b.name)
  );
  person.summary = summary;
  person.library = blob;
  person.libraryName = name;
  person.updated = new Date().toISOString();

  await transact(PEOPLE_STORE, "readwrite", (store) => request(store, "put", person));
  return person.devices;
}

/** Drop the stored library but keep the person and which devices they have. */
export async function forgetLibrary(id) {
  const person = await getPerson(id);
  if (!person) return;
  person.library = null;
  person.libraryName = "";
  person.summary = {};
  person.updated = new Date().toISOString();
  await transact(PEOPLE_STORE, "readwrite", (store) => request(store, "put", person));
}

/** Which person was last in use, so the page opens where it was left. */
export function rememberCurrentPerson(id) {
  try {
    if (id) localStorage.setItem("braid.person", id);
    else localStorage.removeItem("braid.person");
  } catch {
    // A private window without storage still works, it just forgets.
  }
}

export function currentPersonId() {
  try {
    return localStorage.getItem("braid.person");
  } catch {
    return null;
  }
}

/**
 * Close the connection and forget it.
 *
 * Closing matters: an open connection blocks deleteDatabase indefinitely, so
 * merely dropping the reference would leave the database wedged.
 */
export function resetConnection() {
  if (openDb) {
    openDb.close();
    openDb = null;
  }
  dbPromise = null;
}
