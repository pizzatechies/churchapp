"""
Make both apps installable (Android, iOS, Windows, macOS, Linux) as Progressive Web Apps.

The service worker only caches static files and an offline page — never a
signed-in page — so no financial or personal data is stored on the device.
"""

import hashlib
import json

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

from .models import ChurchProfile

THEME = "#0b1d51"


@login_not_required
@cache_control(max_age=3600)
def manifest(request):
    church = ChurchProfile.cached()
    data = {
        "id": "/",
        "name": f"{settings.APP_NAME} · {church.name}",
        "short_name": settings.APP_SHORT_NAME,
        "description": settings.APP_TAGLINE,
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": THEME,
        "theme_color": THEME,
        "categories": ["lifestyle", "productivity"] if settings.APP_NAME.endswith("Connect") else ["finance", "business"],
        "icons": [
            {"src": static("brand/icons/icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": static("brand/icons/icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": static("brand/icons/maskable-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": static("brand/icons/maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return HttpResponse(json.dumps(data, indent=1), content_type="application/manifest+json")


SERVICE_WORKER = """
const CACHE = "ecclesia-%(version)s";
const OFFLINE_URL = "/offline/";
const PRECACHE = %(precache)s;
const CACHE_STATIC = %(cache_static)s;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("ecclesia-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Pages: always from the network (never cached), with a friendly page when offline.
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }
  // Static files have content-hashed names, so they can be cached forever.
  if (CACHE_STATIC && url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      }))
    );
  }
});
"""


@login_not_required
@cache_control(no_cache=True)
def service_worker(request):
    precache = ["/offline/", static("css/app.css"), static("brand/ecclesia-logo.svg"), static("brand/icons/icon-192.png")]
    # In production static names carry a content hash, so a new release gives a new cache.
    version = hashlib.sha256("|".join(precache).encode()).hexdigest()[:12]
    body = SERVICE_WORKER % {
        "version": version,
        "precache": json.dumps(precache),
        # During development static files change without changing their names: don't cache them.
        "cache_static": "false" if settings.DEBUG else "true",
    }
    response = HttpResponse(body, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


@login_not_required
def offline(request):
    return render(request, "includes/offline.html")
