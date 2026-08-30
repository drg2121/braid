// Keeps the page working with no network.
//
// Someone opening this from a home-screen icon with no signal should still be
// able to combine their backups, so everything the page needs is cached.
//
// The page itself is fetched from the network first whenever there is one.
// Serving a cached page first would mean everyone kept seeing yesterday's
// version until their second visit -- including after a fix -- and the page is
// a few kilobytes, so there is nothing to gain by holding it back. Everything
// else is served from the cache and refreshed quietly afterwards, because the
// SQLite engine is most of the weight and it changes about never.

const CACHE = "braid-v3";

const ASSETS = [
  "./",
  "./index.html",
  "./app.js",
  "./jwlibrary.js",
  "./merge.js",
  "./verify.js",
  "./store.js",
  "./i18n.js",
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

/** Put a copy in the cache, ignoring failures; storage may be full. */
function remember(request, response) {
  const copy = response.clone();
  caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => null);
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  if (new URL(request.url).origin !== self.location.origin) return;

  const wantsPage =
    request.mode === "navigate" ||
    (request.headers.get("accept") || "").includes("text/html");

  if (wantsPage) {
    event.respondWith(
      fetch(request)
        .then((fresh) => {
          if (fresh.ok) remember(request, fresh);
          return fresh;
        })
        .catch(() =>
          caches
            .match(request)
            .then((hit) => hit || caches.match("./index.html"))
            .then((hit) => hit || Response.error())
        )
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((hit) => {
      if (hit) {
        fetch(request)
          .then((fresh) => {
            if (fresh.ok) remember(request, fresh);
          })
          .catch(() => null);
        return hit;
      }
      return fetch(request).then((fresh) => {
        if (fresh.ok) remember(request, fresh);
        return fresh;
      });
    })
  );
});
