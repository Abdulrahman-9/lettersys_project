/**
 * ============================================
 * Service Worker - PWA (قشرة ثابتة فقط)
 * ============================================
 * مبدأ الأمان: لا يُخزَّن أي محتوى مُصادَق (صفحات HTML أو API أو media) إطلاقاً،
 * كي لا تتسرّب بيانات مستخدم إلى آخر على جهاز مشترك عند انقطاع الشبكة.
 * يُخزَّن فقط app shell الثابت (CSS/JS/صفحة عدم الاتصال).
 */

// نسخة ثابتة — زِدها يدوياً عند تحديث الأصول الثابتة.
// (لا تستخدم Date.now: يُبطل التخزين ويعيد بناء الكاش في كل تحميل.)
const CACHE_VERSION = 'v85';
const CACHE_NAME = 'lettersys-' + CACHE_VERSION;

// قشرة التطبيق الثابتة فقط — لا '/' ولا أي صفحة مُصادَقة.
// الأيقونات والخطّ (Cairo) مُضمّنة محلياً (بدل CDN) كي تظهر دائماً عبر الشبكة المحلية/دون إنترنت.
const SHELL_URLS = [
  '/static/app.css',
  '/static/app.js',
  '/static/vendor/bootstrap-icons/bootstrap-icons.css',
  '/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2',
  '/static/vendor/cairo/cairo.css',
  '/offline.html'
];

// Install — تخزين القشرة الثابتة
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll(SHELL_URLS).catch(() => {
        console.warn('SW: تعذّر تخزين بعض ملفات القشرة');
      })
    )
  );
  self.skipWaiting();
});

// Activate — تنظيف الكاش القديم وإخطار العملاء بالتحديث
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(
        names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n))
      ))
      .then(() => self.clients.claim())
      .then(() => self.clients.matchAll())
      .then((clients) => {
        clients.forEach((client) => client.postMessage({
          type: 'UPDATE_AVAILABLE',
          message: 'تحديث جديد متوفر للتطبيق'
        }));
      })
  );
});

// Fetch
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // GET فقط ونفس الأصل
  if (request.method !== 'GET') return;
  if (!request.url.startsWith(self.location.origin)) return;

  const url = new URL(request.url);

  // طلبات التنقّل (صفحات HTML مُصادَقة): الشبكة فقط، وعند الانقطاع صفحة عدم الاتصال.
  // لا تخزين إطلاقاً — هذا هو إصلاح تسرّب البيانات بين المستخدمين.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match('/offline.html'))
    );
    return;
  }

  // نقاط API و media قد تحمل محتوى مُصادَقاً → الشبكة فقط بلا تخزين.
  if (
    url.pathname.startsWith('/books/api/') ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/media/')
  ) {
    event.respondWith(
      fetch(request).catch(() => new Response(
        JSON.stringify({ error: 'Offline' }),
        { status: 503, statusText: 'Service Unavailable', headers: { 'Content-Type': 'application/json' } }
      ))
    );
    return;
  }

  // الأصول الثابتة فقط: cache-first مع تحديث بالخلفية (stale-while-revalidate).
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const network = fetch(request).then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        }).catch(() => cached);
        return cached || network;
      })
    );
    return;
  }

  // أي شيء آخر: الشبكة فقط (مع محاولة كاش كحلّ أخير للأصول فقط).
  event.respondWith(fetch(request).catch(() => caches.match(request)));
});

// تخطّي الانتظار عند طلب العميل
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

console.log('Service Worker: Loaded (' + CACHE_NAME + ')');
