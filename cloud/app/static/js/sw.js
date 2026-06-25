// Service worker for Spotify Auto-Skipper PWA.
// Served from / (root scope) via the /sw.js route so it controls the whole app.
// Strategy: stale-while-revalidate for /static/ assets only.
// Pages and API responses always go to the network so auth state and live
// playback/insights data are never served stale.

const VERSION = '{{VERSION}}';
const CACHE = 'skipper-static-' + VERSION;

const PRECACHE = [
  '/static/css/style.css?v=' + VERSION,
  '/static/js/api.js?v=' + VERSION,
  '/static/js/app.js?v=' + VERSION,
  '/static/js/pwa.js?v=' + VERSION,
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/favicon.ico',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      // allSettled so a single 404 never aborts the whole install
      .then((cache) => Promise.allSettled(PRECACHE.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;       // never touch cross-origin
  if (!url.pathname.startsWith('/static/')) return;       // pages + API: network only

  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req).then((resp) => {
        if (resp && resp.status === 200) {
          const copy = resp.clone();
          caches.open(CACHE).then((cache) => cache.put(req, copy));
        }
        return resp;
      }).catch(() => cached);
      return cached || network;
    })
  );
});
