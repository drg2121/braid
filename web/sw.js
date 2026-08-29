// Keeps the page working with no network.
//
// Someone opening this from a home screen icon in a hall with no signal should
// still be able to combine their backups, so everything the page needs is
// cached on first visit and served from there afterwards.

const CACHE = "jwsync-v1";

const ASSETS = [
  "./",
  "./index.html",
  "./app.js",
  "./jwlibrary.js",
  "./merge.js",
  "./verify.js",
  "./store.js",
  "./wal.js",
  "./icon.svg",
  "./manifest.webmanifest",
  "./vendor/sql-wasm.js",
  "./vendor/sql-wasm.wasm",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      // A single missing asset must not leave the page uninstallable, so each
      // is added on its own and failures are tolerated.
      .then((cache) =>
        Promise.all(ASSETS.map((url) => cache.add(url).catch(() => null)))
      )
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n)))
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) {
    return;
  }

  event.respondWith(
    caches.match(request).then((hit) => {
      if (hit) {
        // Refresh in the background so a later visit gets any update, without
        // making this one wait for the network.
        fetch(request)
          .then((fresh) => {
            if (fresh.ok) caches.open(CACHE).then((c) => c.put(request, fresh));
          })
          .catch(() => null);
        return hit;
      }
      return fetch(request).then((fresh) => {
        if (fresh.ok) {
          const copy = fresh.clone();
          caches.open(CACHE).then((c) => c.put(request, copy));
        }
        return fresh;
      });
    })
  );
});
