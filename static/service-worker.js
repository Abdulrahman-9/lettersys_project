/**
 * ============================================
 * Service Worker - PWA Support with Updates
 * ============================================
 * Service worker with automatic update detection
 */

const CACHE_NAME = 'lettersys-v' + (Date.now() % 10000);
const URLS_TO_CACHE = [
  '/',
  '/static/app.css',
  '/static/app.js',
  '/offline.html'
];

// Install event
self.addEventListener('install', (event) => {
  console.log('Service Worker: Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('Service Worker: Caching app shell');
      return cache.addAll(URLS_TO_CACHE).catch(() => {
        console.warn('Some URLs could not be cached');
      });
    })
  );
  self.skipWaiting();
});

// Activate event with cache cleanup and update notification
self.addEventListener('activate', (event) => {
  console.log('Service Worker: Activating...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            console.log('Service Worker: Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => {
      // Notify all clients about update availability
      return self.clients.matchAll().then((clients) => {
        clients.forEach((client) => {
          client.postMessage({
            type: 'UPDATE_AVAILABLE',
            message: 'تحديث جديد متوفر للتطبيق'
          });
        });
      });
    })
  );
  self.clients.claim();
});

// Fetch event - Network first, fallback to cache
self.addEventListener('fetch', (event) => {
  const { request } = event;
  
  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }
  
  // Skip cross-origin requests
  if (!request.url.startsWith(self.location.origin)) {
    return;
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        // Cache successful responses
        if (response && response.status === 200) {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, responseClone);
          });
        }
        return response;
      })
      .catch(() => {
        // Fallback to cache on network error
        return caches.match(request).then((response) => {
          return response || new Response(
            JSON.stringify({ error: 'Offline' }),
            { status: 503, statusText: 'Service Unavailable' }
          );
        });
      })
  );
});

// Message handler for skip waiting
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

console.log('Service Worker: Loaded');
