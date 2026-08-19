/**
 * Service Worker — 오프라인 검색을 실제로 가능하게 하는 부분.
 *
 * 전략을 자원별로 다르게 쓴다:
 *
 *   사전 payload  cache-first, 재검증 없음
 *     URL에 내용 해시가 들어 있어(wine_terms.<sha12>.json) 캐시 히트는 정의상 정답이다.
 *     조건부 요청조차 필요 없으므로 네트워크가 완전히 없어도 즉시 응답한다.
 *
 *   셸 / JS      network-first, 캐시 폴백
 *     일부러 cache-first를 쓰지 않는다. 앱 코드를 cache-first로 두면 깨진 구버전에
 *     사용자가 영구히 갇힌다. 셸은 작아서 네트워크 우선이 부담되지 않고,
 *     오프라인일 땐 캐시가 받아준다.
 *
 *   /api/*       캐시 안 함
 *     편집은 온라인에서만 가능하다. 캐시된 응답으로 성공한 척하면 안 된다.
 */
const VERSION = 'v1';
const SHELL_CACHE = `wine-shell-${VERSION}`;
const DICT_CACHE = `wine-dict-${VERSION}`;

const SHELL = [
  '/',
  '/demo/index.html',
  '/demo/app.js',
  '/demo/admin.js',
  '/demo/manifest.webmanifest',
  '/src/matcher/matcher.js',
];

self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // 개별 실패가 설치 전체를 막지 않게 한다 — 하나가 404여도 나머지는 캐시된다.
    await Promise.allSettled(SHELL.map(u => cache.add(u)));
    self.skipWaiting();
  })());
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keep = new Set([SHELL_CACHE, DICT_CACHE]);
    for (const k of await caches.keys()) {
      if (!keep.has(k)) await caches.delete(k);
    }
    await self.clients.claim();
  })());
});

const isDictPayload = (url) => /wine_terms\.[0-9a-f]{6,}\.json$/.test(url.pathname);

self.addEventListener('fetch', (e) => {
  const { request } = e;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);

  // 편집 API는 절대 캐시하지 않는다.
  if (url.pathname.startsWith('/api/')) return;

  // 내용주소 사전 payload — cache-first. 오프라인 검색의 핵심.
  if (isDictPayload(url)) {
    e.respondWith((async () => {
      const cache = await caches.open(DICT_CACHE);
      const hit = await cache.match(request);
      if (hit) return hit;
      const res = await fetch(request);
      if (res.ok) {
        cache.put(request, res.clone());
        // 이전 버전 payload는 정리한다 — 556KB짜리가 무한정 쌓이지 않게.
        for (const k of await cache.keys()) {
          if (k.url !== request.url) cache.delete(k);
        }
      }
      return res;
    })());
    return;
  }

  // git 폴백 사전도 캐시해둔다 — Supabase가 죽어도 오프라인이 유지되도록.
  if (url.pathname === '/data/dist/wine_terms.json') {
    e.respondWith((async () => {
      const cache = await caches.open(DICT_CACHE);
      try {
        const res = await fetch(request);
        if (res.ok) cache.put(request, res.clone());
        return res;
      } catch {
        return (await cache.match(request)) || Response.error();
      }
    })());
    return;
  }

  // 셸·JS — network-first, 캐시 폴백.
  if (url.origin === self.location.origin) {
    e.respondWith((async () => {
      const cache = await caches.open(SHELL_CACHE);
      try {
        const res = await fetch(request);
        if (res.ok) cache.put(request, res.clone());
        return res;
      } catch {
        const hit = await cache.match(request) || await cache.match('/demo/index.html');
        return hit || Response.error();
      }
    })());
  }
});
