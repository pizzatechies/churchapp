"""
Finding the church a request is for, and switching the database to its schema.

    <app>/church/<slug>/...   that church (the normal address for every church)
    <app>/platform/...        the platform console (admin app only), in the shared schema
    own domain                a church's own web address, Kingdom plan (Domain table)
    <app>/...                 the church marked "served at the main addresses", if any,
                              otherwise a "find your church" page

For /church/<slug>/ addresses the prefix is moved into the script prefix, so every
existing URL, redirect and reverse() works unchanged and produces addresses that stay
inside that church.
"""

import re
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sessions.exceptions import SessionInterrupted
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import connection
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import get_script_prefix, reverse, set_script_prefix, set_urlconf
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.utils.http import http_date
from django_tenants.utils import get_public_schema_name

from .models import Church, Domain

SEEN_EVERY = timedelta(minutes=10)


def is_public():
    return connection.schema_name == get_public_schema_name()


def current_church():
    tenant = getattr(connection, "tenant", None)
    return tenant if isinstance(tenant, Church) else None


class ChurchMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.prefix_re = re.compile(rf"^/{re.escape(settings.CHURCH_URL_PREFIX)}/([a-z0-9-]+)(/.*)?$")

    def __call__(self, request):
        previous = getattr(connection, "tenant", None)
        previous_prefix = get_script_prefix()
        try:
            response = self.route(request)
            if response is None:
                response = self.get_response(request)
            return response
        finally:
            # Leave the connection and URL prefix as we found them (matters in tests and management code).
            set_script_prefix(previous_prefix)
            if isinstance(previous, Church):
                connection.set_tenant(previous)
            else:
                connection.set_schema_to_public()

    def route(self, request):
        connection.set_schema_to_public()
        # Start from the server's own prefix every time, never one left over from an earlier request.
        script = request.META.get("SCRIPT_NAME", "").rstrip("/")
        set_script_prefix(script + "/")
        request.church = None
        request.church_base = script + "/"
        path = request.path_info
        church = None
        match = self.prefix_re.match(path)
        if match:
            church = Church.objects.select_related("plan").filter(slug=match.group(1)).first()
            if church is None:
                self.public(request)
                return render(request, "tenants/church_not_found.html", {
                    "slug": match.group(1), "members_app": settings.APP_NAME.endswith("Connect")}, status=404)
            if match.group(2) is None:
                return HttpResponseRedirect(request.path + "/")
            base = f"{script}/{settings.CHURCH_URL_PREFIX}/{church.slug}/"
            request.path_info = match.group(2)
            set_script_prefix(base)
            request.church_base = base
        elif path == "/platform" or path.startswith("/platform/"):
            return self.public(request)
        else:
            host = request.get_host().split(":")[0].lower()
            domain = Domain.objects.select_related("tenant", "tenant__plan").filter(domain=host).first()
            church = domain.tenant if domain else Church.objects.select_related("plan").filter(is_default=True).first()
            if church is None:
                return self.public(request)

        request.church = church
        connection.set_tenant(church)
        if not church.is_accessible and not request.path_info.startswith("/healthz/"):
            return render(request, "tenants/church_paused.html", {"church": church}, status=503)
        if not church.last_seen_at or timezone.now() - church.last_seen_at > SEEN_EVERY:
            Church.objects.filter(pk=church.pk).update(last_seen_at=timezone.now())
        return None

    def public(self, request, response=None):
        connection.set_schema_to_public()
        request.urlconf = settings.PUBLIC_SCHEMA_URLCONF
        set_urlconf(request.urlconf)
        return response


def session_cookie_name():
    """Each church (and the platform console) keeps its own sign-in, so being signed in to one never affects another."""
    base = settings.SESSION_COOKIE_NAME
    if is_public():
        return f"{base}_platform"
    church = current_church()
    if church is None or church.is_default:
        return base
    return f"{base}_{church.schema_name}"


class ChurchSessionMiddleware(SessionMiddleware):
    """Django's session middleware with a per-church cookie name (see session_cookie_name)."""

    def process_request(self, request):
        request.session_cookie_name = session_cookie_name()
        request.session = self.SessionStore(request.COOKIES.get(request.session_cookie_name))

    def process_response(self, request, response):
        # Same as Django's SessionMiddleware.process_response, with this church's cookie name.
        name = getattr(request, "session_cookie_name", settings.SESSION_COOKIE_NAME)
        try:
            accessed = request.session.accessed
            modified = request.session.modified
            empty = request.session.is_empty()
        except AttributeError:
            return response
        if name in request.COOKIES and empty:
            response.delete_cookie(name, path=settings.SESSION_COOKIE_PATH, domain=settings.SESSION_COOKIE_DOMAIN,
                                   samesite=settings.SESSION_COOKIE_SAMESITE)
            patch_vary_headers(response, ("Cookie",))
        else:
            if accessed:
                patch_vary_headers(response, ("Cookie",))
            if (modified or settings.SESSION_SAVE_EVERY_REQUEST) and not empty:
                if request.session.get_expire_at_browser_close():
                    max_age = expires = None
                else:
                    max_age = request.session.get_expiry_age()
                    expires = http_date(time.time() + max_age)
                if response.status_code < 500:
                    try:
                        request.session.save()
                    except UpdateError:
                        raise SessionInterrupted("The session was deleted before the request completed.")
                    response.set_cookie(
                        name, request.session.session_key, max_age=max_age, expires=expires,
                        domain=settings.SESSION_COOKIE_DOMAIN, path=settings.SESSION_COOKIE_PATH,
                        secure=settings.SESSION_COOKIE_SECURE or None, httponly=settings.SESSION_COOKIE_HTTPONLY or None,
                        samesite=settings.SESSION_COOKIE_SAMESITE,
                    )
        return response


class PasswordChangeRequiredMiddleware:
    """Someone signing in with a password another person set for them must choose their own first."""

    ALLOWED = ("password", "logout", "static", "healthz", "manifest", "sw.js", "offline")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and request.method == "GET" and self.must_change(user):
            target = self.change_url()
            path = request.path_info
            if target and not any(part in path for part in self.ALLOWED) and request.path != target:
                return redirect(target)
        return self.get_response(request)

    @staticmethod
    def must_change(user):
        if is_public():
            profile = getattr(user, "platform_profile", None)
        else:
            profile = getattr(user, "account_profile", None)
        try:
            return bool(profile and profile.must_change_password)
        except Exception:  # profile table missing during a deploy
            return False

    @staticmethod
    def change_url():
        for name in ("platform:password", "password_change", "portal:password"):
            try:
                return reverse(name)
            except Exception:
                continue
        return None
