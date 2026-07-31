const STATIC_CACHE_NAME = "execution-os-static-v4";
const PRECACHE_URLS = [
  "/manifest.webmanifest",
  "/icon.svg",
  "/icon-192.png",
  "/icon-512.png",
  "/icon-maskable-192.png",
  "/icon-maskable-512.png",
];
const PRIVATE_PATH_PREFIXES = [
  "/api",
  "/auth",
  "/login",
  "/sign-in",
  "/sign-up",
  "/setup",
  "/account",
  "/settings",
];

function hasPrivatePath(url) {
  return PRIVATE_PATH_PREFIXES.some(
    (prefix) => url.pathname === prefix || url.pathname.startsWith(`${prefix}/`),
  );
}

function isCacheableStaticRequest(request, url) {
  if (request.method !== "GET" || url.origin !== self.location.origin) {
    return false;
  }
  if (request.mode === "navigate" || request.destination === "document") {
    return false;
  }
  if (url.search || hasPrivatePath(url)) {
    return false;
  }
  return PRECACHE_URLS.includes(url.pathname) || url.pathname.startsWith("/assets/");
}

function isCacheableStaticResponse(response) {
  if (!response || !response.ok || response.type !== "basic") {
    return false;
  }
  const cacheControl = response.headers.get("cache-control")?.toLowerCase() ?? "";
  return !cacheControl.includes("no-store") && !cacheControl.includes("private");
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key !== STATIC_CACHE_NAME).map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (!isCacheableStaticRequest(event.request, url)) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) {
        return cached;
      }
      return fetch(event.request).then((response) => {
        if (isCacheableStaticResponse(response)) {
          const copy = response.clone();
          event.waitUntil(
            caches.open(STATIC_CACHE_NAME).then((cache) => cache.put(event.request, copy)),
          );
        }
        return response;
      });
    }),
  );
});

function safeNotificationPath(value) {
  if (typeof value !== "string") {
    return "/pulse";
  }
  try {
    const url = new URL(value, self.location.origin);
    if (url.origin !== self.location.origin || hasPrivatePath(url)) {
      return "/pulse";
    }
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return "/pulse";
  }
}

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = {};
  }
  const title = payload.title || "Execution OS";
  const options = {
    body: payload.body || "A proactive update is ready.",
    icon: "/icon-192.png",
    badge: "/icon-maskable-192.png",
    data: { url: safeNotificationPath(payload.data?.url) },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  const url = safeNotificationPath(event.notification.data?.url);
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      const existing = clients.find((client) => "focus" in client);
      if (existing) {
        existing.focus();
        return existing.navigate ? existing.navigate(url) : undefined;
      }
      return self.clients.openWindow(url);
    }),
  );
});
