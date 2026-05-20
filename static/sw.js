// @ts-check
/// <reference lib="webworker" />
// Service Worker for Asset Tracker PWA
// Caches static assets, provides offline fallback, handles push notifications

const CACHE_NAME = "asset-tracker-v14";
const OFFLINE_URL = "/assettracker/static/offline.html";
const STATIC_ASSETS = [
  "/assettracker/static/css/fonts.css?v=2",
  "/assettracker/static/css/main.css?v=20260313b",
  "/assettracker/static/css/receive.css",
  "/assettracker/static/css/scanner.css",
  "/assettracker/static/js/theme.js",
  "/assettracker/static/js/locks.js",
  "/assettracker/static/js/guide.js",
  "/assettracker/static/js/toast.js",
  "/assettracker/static/js/scanner.js",
  "/assettracker/static/js/edit-modal.js",
  "/assettracker/static/img/logo-horizontal.png",
  "/assettracker/static/img/logo-icon.png",
  "/assettracker/static/fonts/inter-400.ttf",
  "/assettracker/static/fonts/inter-500.ttf",
  "/assettracker/static/fonts/inter-600.ttf",
  "/assettracker/static/fonts/inter-700.ttf",
  "/assettracker/static/fonts/barlow-400.ttf",
  "/assettracker/static/fonts/barlow-500.ttf",
  "/assettracker/static/fonts/barlow-600.ttf",
  "/assettracker/static/fonts/barlow-700.ttf",
  "/assettracker/static/fonts/barlow-300.ttf",
  "/assettracker/static/fonts/barlow-condensed-400.ttf",
  "/assettracker/static/fonts/barlow-condensed-600.ttf",
  "/assettracker/static/fonts/barlow-condensed-700.ttf",
  "/assettracker/static/fonts/ibm-plex-mono-400.ttf",
  "/assettracker/static/fonts/ibm-plex-mono-500.ttf",
  "/assettracker/static/icons/icon-192.png",
  OFFLINE_URL,
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting(); // Activate immediately — don't wait for old tabs to close
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim()) // Take control of all open tabs immediately
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Only handle same-origin requests
  if (url.origin !== self.location.origin) return;

  // Static assets: stale-while-revalidate
  if (url.pathname.startsWith("/assettracker/static/")) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        const fetchPromise = fetch(event.request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        });
        return cached || fetchPromise;
      })
    );
    return;
  }

  // Navigation requests: network-first with offline fallback
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(OFFLINE_URL))
    );
  }
});

// Push notification handler
self.addEventListener("push", (event) => {
  let data = { title: "Asset Tracker", body: "You have a new notification." };
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      data.body = event.data.text();
    }
  }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/assettracker/static/icons/icon-192.png",
      badge: "/assettracker/static/icons/icon-96.png",
      tag: data.tag || "default",
      data: { url: data.url || "/assettracker/dashboard" },
    })
  );
});

// Notification click: open the relevant page
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/assettracker/dashboard";
  event.waitUntil(
    clients.matchAll({ type: "window" }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.includes("/assettracker/") && "focus" in client) {
          client.navigate(url);
          return client.focus();
        }
      }
      return clients.openWindow(url);
    })
  );
});
