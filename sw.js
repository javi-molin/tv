
const CACHE_NAME = "que-ver-chile-v1";
const APP_FILES = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icon.svg",
  "./data/tv-data.json"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(APP_FILES))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }

  if (url.pathname.endsWith("/tv-data.json")) {
    event.respondWith(
      fetch(request, { cache: "no-store" })
        .then(response => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME)
              .then(cache => cache.put("./data/tv-data.json", copy));
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match("./data/tv-data.json");
          if (cached) return cached;
          return new Response(
            JSON.stringify({ items: [], status: "offline" }),
            { headers: { "Content-Type": "application/json" } }
          );
        })
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(async () => {
        return (await caches.match("./index.html")) ||
          new Response("No hay conexión. Intenta de nuevo más tarde.", {
            headers: { "Content-Type": "text/plain; charset=utf-8" }
          });
      })
    );
  }
});
