// Keeps the site and the last data it loaded, so it opens offline and from the home screen.
const SHELL = 'optcg-shell-v5';
const DATA = 'optcg-data-v1';
const FILES = ['./', 'index.html', 'app.css', 'app.js', 'events.js', 'icon.svg', 'icon-192.png', 'manifest.webmanifest'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => ![SHELL, DATA].includes(k)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Network first, falling back to the last copy. Data files are stored by path without
// the commit in their URL, so the newest copy of each is what comes back offline.
async function networkFirst(request, cacheName, key) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(request);
    if (res.ok) cache.put(key, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(key);
    if (hit) return hit;
    throw err;
  }
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin === self.location.origin) {
    e.respondWith(networkFirst(req, SHELL, url.pathname.endsWith('/') ? new URL('index.html', url).href : url.href.split('#')[0].split('?')[0]));
  } else if (url.hostname === 'raw.githubusercontent.com') {
    // /owner/repo/<commit or branch>/data/... -> data/...
    const path = url.pathname.split('/').slice(4).join('/');
    e.respondWith(networkFirst(req, DATA, `https://optcg.data/${path}`));
  }
});
