// TR Admin PWA - Service Worker v1.0
const CACHE_NAME = 'tr-admin-v1';
const STATIC_CACHE = 'tr-admin-static-v1';
const DYNAMIC_CACHE = 'tr-admin-dynamic-v1';

// الملفات الثابتة للتخزين المسبق
const PRECACHE_URLS = [
  '/dashboard',
  '/static/css/style.css',
  '/static/js/main.js',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg',
  '/static/manifest.json'
];

// التثبيت - تخزين الملفات الثابتة
self.addEventListener('install', event => {
  console.log('[SW] Installing service worker...');
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then(cache => {
        console.log('[SW] Pre-caching static assets');
        return cache.addAll(PRECACHE_URLS);
      })
      .then(() => self.skipWaiting())
      .catch(err => {
        console.warn('[SW] Pre-cache failed (non-critical):', err);
        return self.skipWaiting();
      })
  );
});

// التفعيل - حذف الكاش القديم
self.addEventListener('activate', event => {
  console.log('[SW] Activating service worker...');
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.filter(key => key !== STATIC_CACHE && key !== DYNAMIC_CACHE)
            .map(key => {
              console.log('[SW] Removing old cache:', key);
              return caches.delete(key);
            })
      );
    }).then(() => self.clients.claim())
  );
});

// استراتيجية الشبكة أولاً مع fallback للكاش
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // تجاهل الطلبات غير HTTP
  if (!url.protocol.startsWith('http')) return;

  // API requests — شبكة فقط (لا كاش)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request).catch(() => {
        return new Response(JSON.stringify({
          error: 'أنت غير متصل بالإنترنت',
          offline: true
        }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        });
      })
    );
    return;
  }

  // الملفات الثابتة — كاش أولاً
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return fetch(request).then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(STATIC_CACHE).then(cache => cache.put(request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // صفحات الأدمن — شبكة أولاً مع كاش احتياطي
  if (url.pathname.startsWith('/admin/') || url.pathname === '/dashboard') {
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(DYNAMIC_CACHE).then(cache => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => {
          return caches.match(request).then(cached => {
            if (cached) return cached;
            // صفحة الأوفلاين
            return new Response(offlinePage(), {
              status: 503,
              headers: { 'Content-Type': 'text/html; charset=utf-8' }
            });
          });
        })
    );
    return;
  }

  // بقية الطلبات — شبكة مع fallback
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
});

// صفحة الأوفلاين
function offlinePage() {
  return `<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>غير متصل - TR Admin</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Tajawal', sans-serif;
      background: #0f0f1a;
      color: #e2e8f0;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      text-align: center;
      padding: 2rem;
    }
    .offline-container {
      max-width: 400px;
    }
    .offline-icon {
      font-size: 4rem;
      margin-bottom: 1.5rem;
      opacity: 0.6;
    }
    h1 {
      font-size: 1.5rem;
      margin-bottom: 0.75rem;
      color: #a29bfe;
    }
    p {
      font-size: 1rem;
      opacity: 0.7;
      margin-bottom: 2rem;
      line-height: 1.6;
    }
    .retry-btn {
      background: linear-gradient(135deg, #6c5ce7, #a29bfe);
      color: white;
      border: none;
      padding: 0.75rem 2rem;
      border-radius: 12px;
      font-size: 1rem;
      font-family: inherit;
      cursor: pointer;
      transition: transform 0.2s;
    }
    .retry-btn:active { transform: scale(0.95); }
  </style>
  <link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700&display=swap" rel="stylesheet">
</head>
<body>
  <div class="offline-container">
    <div class="offline-icon">📡</div>
    <h1>غير متصل بالإنترنت</h1>
    <p>لا يمكن الوصول للوحة التحكم حالياً. تأكد من اتصالك بالإنترنت وحاول مرة أخرى.</p>
    <button class="retry-btn" onclick="location.reload()">إعادة المحاولة</button>
  </div>
</body>
</html>`;
}
