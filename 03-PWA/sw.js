/* 学习操作系统 · Service Worker
   策略：预缓存全部静态资源 → 完全离线可用。
   这是"教育平权"的硬要求：断网后核心功能不能失效。 */

const CACHE = 'learnos-v12';
const ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './contract.js',
  './local-adapter.js',
  './migrate.js',
  './icons/icon-192.png',
  './icons/icon-512.png'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(ASSETS))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;

  // 导航请求：缓存优先（离线可用），失败回落 index.html
  if (req.mode === 'navigate') {
    e.respondWith(
      caches.match('./index.html')
        .then(r => r || fetch(req))
        .catch(() => caches.match('./index.html'))
    );
    return;
  }

  // 静态资源：缓存优先 + 后台更新
  e.respondWith(
    caches.match(req).then(hit => {
      const net = fetch(req).then(res => {
        if (res && res.status === 200 && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
        }
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
