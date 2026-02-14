// TR Store Customer PWA - Service Worker v1.0
const CACHE_VERSION = 'tr-store-v1.0';
const STATIC_CACHE = 'tr-store-static-v1.0';
const DYNAMIC_CACHE = 'tr-store-dynamic-v1.0';
const IMG_CACHE = 'tr-store-images-v1.0';

const PRECACHE_URLS = [
  '/',
  '/categories',
  '/static/css/style.css',
  '/static/js/main.js',
  '/static/customer-manifest.json',
  '/static/icons/app-icon-192.png',
  '/static/icons/app-icon-512.png'
];

// التثبيت
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  );
});

// التفعيل - حذف الكاش القديم
self.addEventListener('activate', event => {
  const validCaches = [STATIC_CACHE, DYNAMIC_CACHE, IMG_CACHE];
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k.startsWith('tr-store-') && !validCaches.includes(k))
            .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// Fetch
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  if (!url.protocol.startsWith('http')) return;

  // طلبات خارجية (صور imgur, CDN, خطوط) — تمر مباشرة
  if (url.origin !== self.location.origin) return;

  // API — شبكة فقط
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request).catch(() =>
        new Response(JSON.stringify({ error: 'غير متصل', offline: true }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        })
      )
    );
    return;
  }

  // ملفات ثابتة — كاش أولاً
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(res => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(STATIC_CACHE).then(c => c.put(request, clone));
          }
          return res;
        });
      })
    );
    return;
  }

  // صفحات لوحة التحكم — لا تتدخل
  if (url.pathname.startsWith('/admin/') || url.pathname === '/dashboard') {
    return;
  }

  // صفحات العملاء — شبكة أولاً مع كاش
  event.respondWith(
    fetch(request)
      .then(res => {
        if (res.ok && request.method === 'GET') {
          const clone = res.clone();
          caches.open(DYNAMIC_CACHE).then(c => c.put(request, clone));
        }
        return res;
      })
      .catch(() =>
        caches.match(request).then(cached => {
          if (cached) return cached;
          if (request.headers.get('accept')?.includes('text/html')) {
            return new Response(offlinePage(), {
              status: 503,
              headers: { 'Content-Type': 'text/html; charset=utf-8' }
            });
          }
        })
      )
  );
});

function offlinePage() {
  return `<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>غير متصل - TR Store</title>
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{font-family:'Tajawal',sans-serif;background:#0f0f1a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;padding:2rem}
    .container{max-width:380px}
    .icon{font-size:5rem;margin-bottom:1.5rem;animation:float 3s ease-in-out infinite}
    @keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-15px)}}
    h1{font-size:1.5rem;margin-bottom:0.75rem;background:linear-gradient(135deg,#6c5ce7,#a29bfe);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
    p{font-size:1rem;opacity:0.6;margin-bottom:2rem;line-height:1.8}
    .btn{background:linear-gradient(135deg,#6c5ce7,#a29bfe);color:#fff;border:none;padding:14px 40px;border-radius:14px;font-size:1rem;font-family:inherit;cursor:pointer;transition:all 0.3s;box-shadow:0 4px 15px rgba(108,92,231,0.4)}
    .btn:active{transform:scale(0.95)}
  </style>
  <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap" rel="stylesheet">
</head>
<body>
  <div class="container">
    <div class="icon">📡</div>
    <h1>غير متصل بالإنترنت</h1>
    <p>تأكد من اتصالك بالإنترنت وحاول مرة أخرى للوصول إلى متجر TR</p>
    <button class="btn" onclick="location.reload()">إعادة المحاولة</button>
  </div>
</body>
</html>`;
}
