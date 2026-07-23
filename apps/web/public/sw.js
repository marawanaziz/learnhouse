/* Birth & Baby University — minimal service worker.
 * Present so the app is installable (Chrome/Android require an active SW with a
 * fetch handler for the install prompt). Network-first, no aggressive caching:
 * an LMS must always serve fresh course content, so we never cache HTML/API —
 * we only satisfy the installability contract and provide a tiny offline shell. */
const OFFLINE_URL = '/offline.html'
const SHELL_CACHE = 'bbu-shell-v1'

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((c) => c.addAll([OFFLINE_URL]).catch(() => {}))
  )
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k)))
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return
  // Navigation requests: network-first, fall back to the offline shell.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() => caches.match(OFFLINE_URL))
    )
  }
  // Everything else: pass through to the network (no stale content).
})
