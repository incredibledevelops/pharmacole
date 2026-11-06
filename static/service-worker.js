/* Pharmacole service worker — offline POS + push
 *
 * Cache strategy
 *   - Sensitive routes (/auth/, /payments/, /api/session-token, /webhooks/,
 *     /healthz): never cached, always network. Return a 503 JSON stub when
 *     the network is down so callers don't hang.
 *   - API GETs (/api/…): network-first with runtime cache.
 *   - HTML navigations: network-first with runtime cache, falling back to
 *     `/offline.html` when both network and cache miss.
 *   - Static assets (/static/, /uploads/): cache-first (shell cache).
 *   - Third-party (fonts, CDN): stale-while-revalidate.
 *
 * Every `cache.put()` is awaited and wrapped in try/catch because Response
 * bodies are single-use streams; an unawaited put during a streaming
 * response silently throws in Chrome.
 */
const VERSION = 'v1.1.1';
const SHELL_CACHE = `pharmacole-shell-${VERSION}`;
const RUNTIME_CACHE = `pharmacole-runtime-${VERSION}`;

/* Shell assets fetched at install time — must exist on the server. */
const SHELL_ASSETS = [
  '/',
  '/offline.html',
  '/static/manifest.json',
  '/static/logo.svg',
  '/static/js/pos.js',
  '/static/js/offline-pos.js',
];

/* Paths that must NEVER be cached (auth flows, billing, tokens, webhooks). */
const UNCACHEABLE_PREFIXES = [
  '/auth/',
  '/payments/',
  '/api/session-token',
  '/webhooks/',
];

function isUncacheable(url) {
  if (url.pathname === '/healthz') return true;
  return UNCACHEABLE_PREFIXES.some(p => url.pathname.startsWith(p));
}

/* ------------------------------------------------------------------ */
/* Lifecycle                                                           */
/* ------------------------------------------------------------------ */

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // `cache.addAll` rejects the entire install if ANY asset 404s.
    // Add individually so one missing file doesn't break the SW.
    await Promise.all(
      SHELL_ASSETS.map(async (path) => {
        try {
          const resp = await fetch(path, { cache: 'reload' });
          if (resp.ok) await cache.put(path, resp);
        } catch (e) {
          // Skip missing assets — don't fail the install.
          console.warn('[SW] shell asset failed:', path, e);
        }
      })
    );
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys
        .filter(k => k !== SHELL_CACHE && k !== RUNTIME_CACHE)
        .map(k => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

/* ------------------------------------------------------------------ */
/* Fetch                                                               */
/* ------------------------------------------------------------------ */

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Bypass: sensitive routes and non-GET mutations go straight to network.
  if (isUncacheable(url)) return;

  if (req.method !== 'GET') {
    event.respondWith(networkOnlyJSON(req));
    return;
  }

  // API GETs — network first, cached JSON on offline.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(req, RUNTIME_CACHE, { offlineJson: true }));
    return;
  }

  // Same-origin: differentiate HTML navigation vs static asset.
  if (url.origin === self.location.origin) {
    const isStatic = /^\/(static|uploads)\//.test(url.pathname);
    const isNavigation =
      req.mode === 'navigate' ||
      (req.headers.get('accept') || '').includes('text/html');

    if (isNavigation) {
      event.respondWith(networkFirstHTML(req));
      return;
    }
    if (isStatic) {
      event.respondWith(cacheFirst(req, SHELL_CACHE));
      return;
    }
    // Other same-origin (e.g. /manifest.json) — network first, cached fallback.
    event.respondWith(networkFirst(req, RUNTIME_CACHE));
    return;
  }

  // Third-party (fonts, CDN): stale-while-revalidate.
  event.respondWith(staleWhileRevalidate(req, RUNTIME_CACHE));
});

/* ------------------------------------------------------------------ */
/* Strategies                                                          */
/* ------------------------------------------------------------------ */

/**
 * Network-only with a JSON stub if offline.
 * Used for non-GET requests so fetch() callers get a real Response.
 */
async function networkOnlyJSON(req) {
  try {
    return await fetch(req);
  } catch (e) {
    return new Response(
      JSON.stringify({ error: 'offline', offline: true }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }
    );
  }
}

/**
 * Cache-first. Best for immutable assets (css, js, images, fonts).
 * On cache miss: fetch, cache if ok, return. On network failure: serve
 * the app-shell `/offline.html` if we have it, otherwise a minimal 503.
 */
async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  if (cached) return cached;

  try {
    const resp = await fetch(req);
    if (resp && resp.ok) {
      // Clone BEFORE the caller consumes the stream.
      try { await cache.put(req, resp.clone()); } catch (e) { /* quota */ }
    }
    return resp;
  } catch (e) {
    const offline = await caches.match('/offline.html');
    if (offline) return offline;
    return new Response('Offline', {
      status: 503,
      headers: { 'Content-Type': 'text/plain' },
    });
  }
}

/**
 * Network-first for HTML navigations. On network failure, serve the
 * cached page (if any), then `/offline.html`, then a minimal 503.
 *
 * This ensures a cashier who reloads `/cashier/pos` offline gets a real
 * page — never a JSON blob.
 */
async function networkFirstHTML(req) {
  const cache = await caches.open(RUNTIME_CACHE);
  try {
    const resp = await fetch(req);
    if (resp && resp.ok) {
      try { await cache.put(req, resp.clone()); } catch (e) { /* quota */ }
    }
    return resp;
  } catch (e) {
    const cached = await cache.match(req);
    if (cached) return cached;
    const offline = await caches.match('/offline.html');
    if (offline) return offline;
    return new Response('Offline', {
      status: 503,
      headers: { 'Content-Type': 'text/plain' },
    });
  }
}

/**
 * Network-first with cached fallback. Used for API GETs and other
 * same-origin non-navigation requests.
 *
 * When `offlineJson` is true, returns a JSON `{offline:true}` stub if
 * both network and cache miss (callers expect JSON).
 */
async function networkFirst(req, cacheName, opts) {
  const offlineJson = !!(opts && opts.offlineJson);
  const cache = await caches.open(cacheName);

  try {
    const resp = await fetch(req);
    if (resp && resp.ok) {
      try { await cache.put(req, resp.clone()); } catch (e) { /* quota */ }
    }
    return resp;
  } catch (e) {
    const cached = await cache.match(req);
    if (cached) return cached;
    if (offlineJson) {
      return new Response(
        JSON.stringify({ error: 'offline', offline: true }),
        { status: 503, headers: { 'Content-Type': 'application/json' } }
      );
    }
    return new Response('Offline', {
      status: 503,
      headers: { 'Content-Type': 'text/plain' },
    });
  }
}

/**
 * Stale-while-revalidate. Returns cached immediately (if any) and
 * refreshes in the background. The returned `fetchPromise` is only
 * used if there's no cache.
 */
async function staleWhileRevalidate(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);

  const networkPromise = fetch(req)
    .then(async (resp) => {
      if (resp && resp.ok) {
        try { await cache.put(req, resp.clone()); } catch (e) { /* quota */ }
      }
      return resp;
    })
    .catch(() => cached);

  return cached || networkPromise;
}

/* ------------------------------------------------------------------ */
/* Push notifications                                                  */
/* ------------------------------------------------------------------ */

self.addEventListener('push', (event) => {
  let payload = { title: 'Pharmacole', body: 'New notification', url: '/' };
  try {
    const data = event.data ? event.data.json() : null;
    if (data && typeof data === 'object') payload = { ...payload, ...data };
  } catch (e) {
    // Non-JSON payload — fall back to defaults.
  }

  event.waitUntil(
    self.registration.showNotification(payload.title || 'Pharmacole', {
      body: payload.body || '',
      icon: payload.icon || '/static/logo.svg',
      badge: payload.badge || '/static/logo.svg',
      data: { url: payload.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';
  const targetPath = (() => {
    try { return new URL(target, self.location.origin).pathname; }
    catch (e) { return '/'; }
  })();

  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    // Prefer a window already on the same path.
    for (const c of windows) {
      try {
        const cPath = new URL(c.url).pathname;
        if (cPath === targetPath && 'focus' in c) {
          return c.focus();
        }
      } catch (e) { /* ignore malformed urls */ }
    }
    // Then prefer any controlled tab on our origin.
    for (const c of windows) {
      try {
        if (new URL(c.url).origin === self.location.origin && 'focus' in c) {
          c.navigate(target).catch(() => {});
          return c.focus();
        }
      } catch (e) { /* ignore */ }
    }
    // Otherwise open a fresh tab.
    if (self.clients.openWindow) {
      return self.clients.openWindow(target);
    }
  })());
});