// Keeps the page working with no network.
//
// Someone opening this from a home-screen icon with no signal should still be
// able to combine their backups, so everything the page needs is cached.
//
// The page and its own scripts are fetched from the network first, together.
// Serving a cached script beside a fresh page is worse than being slow: the
// two are one program, and an old app.js against a new index.html looks for
// elements that no longer exist and dies before the page can start. Both are a
// few kilobytes. Only the vendored SQLite engine is served from the cache
// first, because it is most of the weight and changes about never.

const CACHE = "braid-v5";

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

  // Everything this app is made of travels together; only the vendored engine
  // is allowed to come from the cache ahead of the network.
  const url = new URL(request.url);
  const vendored = url.pathname.includes("/vendor/");
  const together =
    !vendored &&
    (request.mode === "navigate" ||
      (request.headers.get("accept") || "").includes("text/html") ||
      url.pathname.endsWith(".js") ||
      url.pathname.endsWith(".mjs") ||
      url.pathname.endsWith(".webmanifest"));

  if (together) {
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
