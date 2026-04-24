const CACHE = "paradise-shine-v1";
const SHELL = ["/", "/logo.jpg", "/icon-192.png", "/icon-512.png", "/icon-apple.png"];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", e => {
  // Always go to network for API calls
  if (e.request.url.includes("/verify-pin")) {
    e.respondWith(fetch(e.request));
    return;
  }
  // Cache-first for everything else (app shell, logo, icons)
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
