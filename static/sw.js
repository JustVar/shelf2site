// Tombstone service worker: unregister any previously-installed worker and
// clear its caches. The Asset Tracker no longer ships a service worker; this
// file exists only so already-installed workers self-remove on their next
// update check. Safe to delete once clients have cycled.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    await self.registration.unregister();
    for (const key of await caches.keys()) {
      await caches.delete(key);
    }
    for (const client of await self.clients.matchAll()) {
      client.navigate(client.url);
    }
  })());
});
