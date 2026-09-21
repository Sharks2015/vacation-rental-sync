// Cache version only controls the storage bucket — it no longer gates updates.
// The page is fetched network-first, so edits to index.html reach every device
// on the next load without anyone bumping a version string.
const CACHE = 'psc-v38';
const PRECACHE = ['/', '/index.html', '/logo.jpg', '/icon-192.png', '/icon-512.png', '/manifest.json'];

// Only these are safe to serve from cache. Anything else (every API route,
// including /history and the manager endpoints) always goes to the network.
const STATIC_RE = /\.(?:css|png|jpg|jpeg|svg|ico|webp|woff2?)$/i;
const STATIC_PATHS = new Set(['/manifest.json']);

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function putInCache(req, res) {
  if (res && res.ok) {
    const copy = res.clone();
    caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
  }
  return res;
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  const isDoc = req.mode === 'navigate' || url.pathname === '/' || url.pathname === '/index.html';

  // The app shell: network-first, fall back to cache only when offline.
  if (isDoc) {
    e.respondWith(
      fetch(req)
        .then(res => putInCache('/index.html', res))
        .catch(() => caches.match('/index.html').then(c => c || caches.match('/')))
    );
    return;
  }

  // Static assets: serve instantly from cache, refresh in the background.
  if (STATIC_PATHS.has(url.pathname) || STATIC_RE.test(url.pathname)) {
    e.respondWith(
      caches.match(req).then(cached => {
        const network = fetch(req).then(res => putInCache(req, res)).catch(() => cached);
        return cached || network;
      })
    );
    return;
  }

  // Everything else (API calls) is left alone — never cached, never stale.
});
