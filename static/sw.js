self.addEventListener('install', function (event) {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

// Do not cache business pages or uploads. This service worker is intentionally
// minimal so the system can be installed like an app without serving stale data.
self.addEventListener('fetch', function () {});
